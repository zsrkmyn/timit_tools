import sys, pickle
from collections import defaultdict

unigrams = defaultdict(int)
bigrams = defaultdict(lambda: defaultdict(int))

def process(f):
    previous = None
    for line in f:
        if line[0].isdigit():
            current = line.rstrip('\n').split()[2]
            if previous != None:
                bigrams[previous][current] += 1
            unigrams[current] += 1
            previous = current
        else:
            previous = None
    s = sum(unigrams.values())
    uni = dict(unigrams)
    bi = dict(bigrams)
    for phn in uni.keys():
        uni[phn] *= 1.0 / s
    discounts = {}
    for phn, d in bi.items():
        s = sum(d.values())
        for phn2 in d.keys():
            bi[phn][phn2] -= 0.5 # DISCOUNT
            bi[phn][phn2] *= 1.0 / s
        discounts[phn] = 1.0 - sum(bi[phn].values())
    print(uni)
    print(bi)
    print(discounts)
    print(sum(discounts.values()))

    with open('bigram.pickle', 'w') as of:
        pickle.dump((uni, bi, discounts), of)
    print(">>> pickled bigram.pickle containing (unigrams, bigrams) dicts")

if len(sys.argv) < 2:
    print("python produce_LM.py train.mlf")

with open(sys.argv[1]) as f: 
    process(f)
