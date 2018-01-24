#!/bin/sh

set -e

data_root=$1
config=$2

for i in "${data_root}/"*.song; do
	echo "run with song dir: $i"
	for s in "$i/"*.m4a; do
		song="${s%%.m4a}"
		echo "run with audio $song"
		sox "$s" "${song}.wav"
		HCopy -C "$config" "${song}.wav" "${song}.mfc" &
	done
	wait
	rm "$i/"*.wav
	ls "$i/"*.mfc > "$i/list.scp"
done
