TMP_TRAIN_FOLDER=tmp_TIMIT_train_dev_test_$(date +%s)
make prepare_timit dataset=$1
make train_monophones_monogauss dataset_train_folder=$1/train TMP_TRAIN_FOLDER=${TMP_TRAIN_FOLDER}
make tweak_silence_model dataset_train_folder=$1/train TMP_TRAIN_FOLDER=${TMP_TRAIN_FOLDER}
