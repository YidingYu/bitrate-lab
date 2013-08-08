import pylab
import numpy
import math
import sys
import matplotlib.cm as cm
import rates
import harness

def badness(rix, prob):
    txtime = harness.tx_time(rix, 1500)
    score = 0
    likeliness = 1
    for i in range(0, 10):
        score += likeliness * prob * (txtime + harness.difs(rix))
        txtime += txtime + harness.backoff(rix, i + 1)
        likeliness *= (1 - prob)
    score += likeliness * (txtime + harness.difs(rix))
    return score

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        print("USAGE: python draw_trace.py [datafile]")
        exit()

    datfile = sys.argv[1]
    dat = eval(open(datfile, "rt").read())

    start, rates, end = dat

    width = 100
    img = numpy.zeros((len(rates), width))
    best = numpy.zeros(width)

    idx = [0] * len(rates)

    for i in range(0, width):
        t = (i + .5) / width * (end - start) + start
        ps = [harness.packet_stats(rates, t, r) for r, _ in enumerate(rates)]
        badnesses = [badness(rix, p) / 1e6 for rix, p in enumerate(ps)]
        best[i] = numpy.argmin(badnesses)
        img[:, i] = ps

    fig, ax = pylab.subplots()
    ax.set_xlim(0, width)
    ax.set_ylim(0, 11)

    ax.imshow(img, cmap=cm.Blues, interpolation='nearest', aspect="auto")
    ax.plot(range(width), best, 'r', linewidth=2)

    pylab.show()
