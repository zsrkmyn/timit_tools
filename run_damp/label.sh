#!/bin/sh

data_root="$1"
train_folder="$2"
hmm_name="$3"

for i in "${data_root}/"*.song; do
	#echo "run with song dir: $i"
	echo $i
done | parallel -j22 \
	HVite -p 2.5 -s 5.0 \
		-w "${train_folder}/wdnet" \
		-H "${train_folder}/${hmm_name}/hmmdefs" \
		-H "${train_folder}/${hmm_name}/macros" \
		-i "{1}/outtrans_${hmm_name}.mlf" \
		-S "{1}/list.scp" \
		"${train_folder}/dict" "${train_folder}/phones"
