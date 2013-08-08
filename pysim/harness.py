from __future__ import print_function
from __future__ import division
import time
import rates
import os, sys
import random

DEBUG = "DEBUG" in os.environ

def load_data(source):
    return eval(open(source, "rt").read())

WINDOW = 1e7 # 10ms
LUOPS = 0
CACHE = [[0, WINDOW] for r in rates.RATES]
def packet_stats(data, time, rate):
    global LUOPS

    txs = []
    while not txs:
        idx, w = CACHE[rate]
        CACHE[rate][0] = 0

        for i in range(idx, len(data[rate])):
            t, success, delay = data[rate][i]
            LUOPS += 1

            if abs(t - time) < w:
                txs.append((success, delay))
                if not CACHE[rate][0]:
                    CACHE[rate][0] = i
                    CACHE[rate][1] = min(w / 1.5, WINDOW)

            if t > w + time:
                break

        CACHE[rate][1] *= 2

    successful = [tx for tx in txs if tx[0]]

    return len(successful) / len(txs)


# The test harness uses a calculation of transmission time based on
# that in the SampleRate paper
BACKOFF = { "ofdm": [0], "ds": [0], "dsss": [0] }
for i in range(5, 11):
    BACKOFF["ds"].append(int(((2**i) - 1) * (20 / 2)))
for i in range(5, 11):
    BACKOFF["dsss"].append(int(((2**i) - 1) * (9 / 2)))
for i in range(4, 11):
    BACKOFF["ofdm"].append(int(((2**i) - 1) * (9 / 2)))

def backoff(rix, attempt):
    return BACKOFF[rates.RATES[rix].phy][min(attempt, len(BACKOFF) - 1)] * 1000

def difs(rix):
    version = "g" if rates.RATES[rix].phy == "ofdm" else "b"
    return (50 if version == "b" else 28) * 1000

def tx_time(rix, nbytes):
    # From the SampleRate paper.  See samplerate.py for annotated version.
    bitrate = rates.RATES[rix].mbps
    version = "g" if rates.RATES[rix].phy == "ofdm" else "b"
    sifs = 10 if version == "b" else 9
    ack = 304 # Somehow 6mb acks aren't used
    header = 192 if bitrate == 1 else 96 if version == "b" else 20

    return (sifs + ack + header + (nbytes * 8 / bitrate)) * 1000 # 1000 = us / ns

class Harness:
    def __init__(self, data, choose_rate, push_statistics):
        self.start = data[0]
        self.data = data[1]
        self.end = data[2]

        self.clock = data[0]
        self.choose_rate = choose_rate
        self.push_statistics = push_statistics

        self.histogram = [[0, 0, 0, 0, 0] for i in rates.RATES]

        self.attempts = 0

    def send_one(self, rate, is_success):
        delay = tx_time(rate, 1500)
        rateinfo = self.histogram[rate]

        rateinfo[0] += 1 # total packets
        rateinfo[1] += 1 if is_success else 0
        rateinfo[2] += delay

        if is_success:
            delay += difs(rate)
            self.attempts = 0
        else:
            self.attempts += 1
            backoff_t = backoff(rate, self.attempts)
            rateinfo[3] += backoff_t
            delay += backoff_t

        rateinfo[4] += delay
        return delay

    def send_packet(self):
        rate_arr = self.choose_rate(self.clock)

        if DEBUG:
            print("Sending packet at:", end=" ")
            for (rate, tries) in rate_arr:
                print("Rate {}/{}".format(rate, tries), end=" ")
            print()

        tot_delay = 0
        tot_tries = []
        tot_status = None
        for (rate, tries) in rate_arr:
            p_success = packet_stats(self.data, self.clock, rate)

            s_tries = 0
            succeeded = False
            for i in range(tries):
                success = random.random() < p_success
                s_tries += 1
                tot_delay += self.send_one(rate, success)

                if success:
                    succeeded = True
                    break

            tot_tries.append((rate, s_tries))

            if succeeded:
                tot_status = True
                break
        else:
            tot_status = False # Failure

        if DEBUG:
            print(" => {}: {} ns".format("Good" if tot_status else "Fail",
                                         tot_delay), end=" ")
            for (rate, tries) in tot_tries:
                print("Rate {}/{}".format(rate, tries), end=" ")
            print()

        self.push_statistics(tot_status, self.clock, tot_delay, tot_tries)

        self.clock += tot_delay
        return tot_status

    def run(self):
        self.clock = self.start

        good = 0
        bad = 0
        print("Please wait, running simulation:     ", end="")
        lenlast = 0
        try:
            old_pct = None
            while self.clock < self.end:
                pct = int(100 * (self.clock-self.start) / (self.end-self.start))

                if pct != old_pct:
                    print("\b" * lenlast, end="")
                    msg = "{: 3d}%, {}".format(pct, LUOPS)
                    lenlast = len(msg)
                    print(msg, end="")
                    sys.stdout.flush()

                old_pct = pct

                status = self.send_packet()
                if status:
                    good += 1
                else:
                    bad += 1
        except KeyboardInterrupt as e:
            pass
        print()

        time = self.clock - self.start

        return time, good, bad

if __name__ == "__main__":
    if len(sys.argv) > 2:
        alg = sys.argv[1]
        data_file = sys.argv[2]
    else:
        print("USAGE: harness.py <algorithm> <data-file> [seed]")
        sys.exit()

    if len(sys.argv) >= 4:
        seed = int(sys.argv[3])
    else:
        seed = random.randint(0, sys.maxsize)

    random.seed(seed)
    print("Running with random seed {}".format(seed))

    os.environ["DATA"] = data_file
    data = load_data(data_file)
    module = __import__(alg)
    harness = Harness(data, module.apply_rate, module.process_feedback)
    time, good, bad = harness.run()

    if DEBUG: print()

    print("Simulation ran with {} LUOPS".format(LUOPS))
    print("[summary] {:.2f} s to send {} packets (and {} failures)".format(time / 1e9, good, bad))
    throughput = 1500 * 8 * good / (time / 1e9) / 1e6
    print("Average packet took {:.3f} ms / achieved {:.3f} Mbps".format(time / good / 1e6, throughput))

    for rate_idx, info in enumerate(harness.histogram):
        tries, successes, sending_t, backoff_t, total_t = info
        if not tries: continue

        sending_t /= 1e9
        backoff_t /= 1e9
        total_t /= 1e9

        mbps = rates.RATES[rate_idx].mbps
        template = "{:>5} Mbps : {:>6} tries ({:>3.0%} success; {:>6.1f}s total)"
        print(template.format(mbps, tries, successes/tries, total_t))
