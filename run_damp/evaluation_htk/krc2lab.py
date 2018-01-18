#!/usr/bin/python3

import re
from nltk.corpus import cmudict

def word_level_offset(decoded, krc_offset=0):
  ret = []
  start_pat = re.compile(r'\[(\d+),\d+\]')
  for line in decoded.splitlines():
    m = start_pat.match(line)
    if m is None:
      continue
    start_time = int(m.groups()[0]) + krc_offset
    line = line[m.span()[1]:]

    sentence = []
    for word in line.split():
      sep1 = word.find(',')
      sep2 = sep1 + 1 + word[sep1+1:].find(',')
      offset = int(word[1:sep1])
      lasting = int(word[sep1+1:sep2])
      word = word[word.find('>')+1:]
      b = start_time + offset
      e = b + lasting
      sentence.append((b, e, word))
    ret.append(sentence)
  return ret

if __name__ == '__main__':
  import sys
  import math
  import os

  ending_zero = re.compile(r'\d$')

  offset_file = os.path.dirname(sys.argv[1]) + '/krc_offset'
  if os.path.isfile(offset_file):
    with open(offset_file, 'r') as f:
      krc_offset = int(f.read())
  else:
    krc_offset = 0

  with open(sys.argv[1], 'r') as f:
    truth = word_level_offset(f.read(), krc_offset)

  truth = tuple(x for sub in truth for x in sub)
  transcr = cmudict.dict()
  phones = iter(transcr.get(w[2].lower(), (['UKN'],))[0] for w in truth)
  phones = tuple(tuple(ending_zero.sub('', p) for p in ps) for ps in phones)

  label = []
  for t, ps in zip(truth, phones):
    b, e = t[0], t[1]
    lasting = e - b
    n = len(ps)
    step = lasting / n
    for p in ps:
      e = math.floor(b + step + 0.5) # +0.5 for round
      label.append((str(b), str(e), p.lower()))
      b = e

  with open(sys.argv[1][:-3]+'lab', 'w') as f:
    f.write('\n'.join(list(map(lambda x: '\t'.join(x), label))))
    f.write('\n')
