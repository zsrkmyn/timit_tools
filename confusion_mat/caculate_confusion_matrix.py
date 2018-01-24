#!/usr/bin/python3

from sortedcontainers import SortedListWithKey
import fileinput
import sys

import numpy as np

dic = {
"iy": 0,
"ix": 1,
"ih": 2,
"eh": 3,
"ae": 4,
"ax": 5,
"ah": 6,
"axh":7,
"uw": 8,
"ux": 9,
"uh": 10,
"ao": 11,
"aa": 12,
"ey": 13,
"ay": 14,
"oy": 15,
"aw": 16,
"ow": 17,
"er": 18,
"axr":19,
"l":  20,
"el": 21,
"r":  22,
"w":  23,
"y":  24,
"m":  25,
"em": 26,
"n":  27,
"en": 28,
"nx": 29,
"ng": 30,
"eng":31,
"v":  32,
"f":  33,
"dh": 34,
"th": 35,
"z":  36,
"s":  37,
"zh": 38,
"sh": 39,
"jh": 40,
"ch": 41,
"b":  42,
"p":  43,
"d":  44,
"dx": 45,
"t":  46,
"g":  47,
"k":  48,
"hh": 49,
"hv": 50,
"bcl":51,
"pcl":52,
"dcl":53,
"tcl":54,
"gcl":55,
"kcl":56,
"q":  57,
"epi":58,
"pau":59,
"!ENTER": 60,
"!EXIT": 61,
}

def parse_mlf(fname, divisor):
  all_label = dict()
  with fileinput.input((fname,), mode='r') as f:
    f.readline()
    for line in f:
      if line.startswith('"'):
        audio_id = line.strip('"\n')[:-4]
        audio_id = audio_id.split('/')[-1]
        labels = SortedListWithKey(key=lambda x: x[0])
        continue

      if line[0] == '.':
        all_label[audio_id] = labels
        continue

      line = line.strip().split()
      if len(line) < 3:
        print('Warning: Invalid line', line)
        continue
      label = (int(line[0]) // divisor, int(line[1]) // divisor, line[2])
      #label = line[2]
      labels.append(label)

  return all_label

def main():
  confusion_mat = np.zeros((len(dic), len(dic)))

  truthground_file = sys.argv[1]
  predicted_file = sys.argv[2]

  predicted = parse_mlf(predicted_file, 10)
  truthground = parse_mlf(truthground_file, 1)

  for audio_id, pred in predicted.items():
    truth = truthground[audio_id]
    end = pred[-1][1]
    i = 0
    print(audio_id)
    while i < end:
      pred_i = pred.bisect_right((i, None, None)) - 1
      truth_i = truth.bisect_right((i, None, None)) - 1
      pred_ph = pred[pred_i][2]
      truth_ph = truth[truth_i][2]
      pred_ph_id = dic[pred_ph]
      truth_ph_id = dic[truth_ph]
      confusion_mat[truth_ph_id, pred_ph_id] += 1
      i += 10000

  confusion_mat /= np.reshape(np.sum(confusion_mat, 1), (-1, 1))
  np.save('./conf_mat.npy', confusion_mat)

if __name__ == '__main__':
  main()
