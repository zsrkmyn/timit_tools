#!/usr/bin/python3

import os
import sys
import fileinput
import math

trans = {
'ih': 'ix',
'ah': 'ax',
'ax-h': 'ax',
'ux': 'uw',
'aa': 'ao',
'axr': 'er',
'el': 'l',
'em': 'm',
'en': 'n',
'nx': 'n',
'eng': 'ng',
'sh': 'zh',
'hv': 'hh',
'bcl': 'unk',
'pcl': 'unk',
'dcl': 'unk',
'tcl': 'unk',
'gcl': 'unk',
'kcl': 'unk',
'q': 'unk',
'epi': 'unk',
'pau': 'unk',
'!ENTER': 'unk',
'!EXIT': 'unk',
}

def parse_mlf(fname):
  all_songs = []
  with fileinput.input((fname,), mode='r') as f:
    f.readline()
    for line in f:
      if line.startswith('"'):
        labels = []
        continue

      if line[0] == '.':
        all_songs.append(labels)
        continue

      line = line.strip().split()
      label = (int(line[0][:-4]), int(line[1][:-4]), line[2])
      labels.append(label)

    return all_songs

def get_window_start(labels, start_time, hint=0):
  start = hint
  while start < len(labels) and labels[start][0] < start_time:
    start += 1
  return start

def get_window_end(labels, start, tol):
  if start >= len(labels):
    return start
  start_time = labels[start][0]
  end_time = start_time + tol * 2
  end = start + 1
  while end < len(labels) and labels[end][0] < end_time:
    end += 1
  return end

if __name__ == '__main__':
  song_dir = sys.argv[1].rstrip('/')
  tol = int(sys.argv[2]) # tolerence in ms

  song_name = song_dir[song_dir.rindex('/')+1:-5]
  detect_file = os.path.join(song_dir, 'outtrans.mlf')
  label_file = os.path.join(song_dir, song_name + '.lab')
  print(detect_file, label_file)

  with open(label_file, 'r') as f:
    labels = f.read()

  labels = labels.splitlines()
  labels = tuple(label.split('\t') for label in labels)
  labels = tuple((int(x[0]), int(x[1]), x[2]) for x in labels)

  detect_songs = parse_mlf(detect_file)

  accs = []
  song_cnt = 0
  for detect_song in detect_songs:
    total = 0
    cnt = 0
    window_start = 0
    for detect_label in detect_song:
      phone = detect_label[2]
      phone = trans.get(phone, phone)
      if phone == 'unk':
        continue
      start_time = detect_label[0]
      window_start = get_window_start(labels, start_time, window_start)
      window_end = get_window_end(labels, window_start, tol)

      candidate = set(x[2] for x in labels[window_start:window_end])

      if phone in candidate:
        cnt += 1
      total += 1

    acc = cnt / total
    accs.append(acc)
    song_cnt += 1
    print('acc:', acc)
  avg_acc = sum(accs) / song_cnt
  std = math.sqrt(sum(math.pow(x - avg_acc, 2) for x in accs)) / song_cnt
  print('avg_acc:', avg_acc)
  print('std:', std)
