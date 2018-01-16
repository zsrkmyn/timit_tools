import numpy as np
import htkmfc
import sys, pickle, functools, os
from multiprocessing import Pool, cpu_count
import scipy.io
sys.path.append(os.getcwd())
sys.path.append('DBN')

from batch_viterbi import precompute_det_inv, phones_mapping, parse_hmm
from batch_viterbi import compute_likelihoods, compute_likelihoods_dbn
from batch_viterbi import viterbi, initialize_transitions
from batch_viterbi import penalty_scale, padding

INSERTION_PENALTY = 2.5 # penalty of inserting a new phone (in the Viterbi)
SCALE_FACTOR = 1.0 # importance of the LM w.r.t. the acoustics
VERBOSE = True
epsilon = 1E-5 # degree of precision for floating (0.0-1.0 probas) operations
epsilon_log = 1E-30 # to add for logs
#APPEND_NAME = '_dbn.mat'
APPEND_NAME = '_grbm.mat'
#APPEND_NAME = '_hmm_dbn.mat'
DEBUG = True # adds asserts...


class InnerLoop(object): # to circumvent pickling pbms w/ multiprocessing.map
    def __init__(self, likelihoods, map_states_to_phones, transitions,
            using_bigram=False, 
            depth_1_likelihoods=None, depth_2_likelihoods=None):
        self.likelihoods = likelihoods
        self.depth_1_likelihoods = depth_1_likelihoods
        self.depth_2_likelihoods = depth_2_likelihoods
        self.likelihoods = likelihoods
        self.map_states_to_phones = map_states_to_phones
        self.transitions = transitions
        self.using_bigram = using_bigram
    def __call__(self, mfcc_file):
        print("doing", mfcc_file)
        start, end = self.likelihoods[1][mfcc_file]
        if VERBOSE:
            print(mfcc_file)
            print(start, end)
        _, posteriorgrams = viterbi(self.likelihoods[0][start:end],
                                   self.transitions, 
                                   self.map_states_to_phones,
                                   using_bigram=self.using_bigram)
        if DEBUG:
            assert(not (posteriorgrams == np.NaN).any())
            assert(not (posteriorgrams < -1000.0).all())
            assert(not (self.depth_1_likelihoods[start:end] == np.NaN).any())
            assert(not (self.depth_2_likelihoods[start:end] == np.NaN).any())
            assert(not (self.likelihoods[0][start:end] == np.NaN).any())
            assert(not (self.likelihoods[0][start:end] < -31.0).all())
        self.write_file(mfcc_file, start, end, posteriorgrams)
    def write_file(self, mfcc_file, start, end, posteriorgrams):
        print(">>> written", mfcc_file)
        scipy.io.savemat(mfcc_file[:-4] + APPEND_NAME, mdict={
            'depth_1_likelihoods': self.depth_1_likelihoods[start:end],
            'depth_2_likelihoods': self.depth_2_likelihoods[start:end],
            'likelihoods': self.likelihoods[0][start:end],
            'posteriors': posteriorgrams})



if __name__ == "__main__":
    usage = "python scores_ABX.py directory input_hmm [input_dbn dbn_dict]"
    if len(sys.argv) != 3 and len(sys.argv) != 5:
        print(usage)
        sys.exit(-1)

    with open(sys.argv[2]) as ihmmf:
        n_states, transitions, gmms = parse_hmm(ihmmf)

    gmms_ = precompute_det_inv(gmms)
    map_states_to_phones = phones_mapping(gmms)
    likelihoods_computer = functools.partial(compute_likelihoods, gmms_)
    depth_1_computer = None
    depth_2_computer = None

    dbn = None
    if len(sys.argv) == 5:
        from DBN_Gaussian_timit import DBN # not Gaussian if no GRBM
        with open(sys.argv[3]) as idbnf:
            dbn = pickle.load(idbnf)
        with open(sys.argv[4]) as idbndtf:
            dbn_to_int_to_state_tuple = pickle.load(idbndtf)
        dbn_phones_to_states = dbn_to_int_to_state_tuple[0]
        depth_1_computer = functools.partial(compute_likelihoods_dbn, dbn, depth=1)
        depth_2_computer = functools.partial(compute_likelihoods_dbn, dbn, depth=2)
        likelihoods_computer = functools.partial(compute_likelihoods_dbn, dbn, depth=None)

    # TODO bigrams
    transitions = initialize_transitions(transitions)
    #print transitions
    transitions = penalty_scale(transitions, insertion_penalty=INSERTION_PENALTY,
            scale_factor=SCALE_FACTOR)

    dummy = np.ndarray((2,2)) # to force only 1 compile of Viterbi's C
    viterbi(dummy, [None, dummy], {}) # also for this compile's debug purposes

    list_of_mfcc_files = []
    for d, ds, fs in os.walk(sys.argv[1]):
        for fname in fs:
            if fname[-4:] != '.mfc':
                continue
            fullname = d.rstrip('/') + '/' + fname
            list_of_mfcc_files.append(fullname)

    if dbn != None:
        input_n_frames = dbn.rbm_layers[0].n_visible / 39 # TODO generalize
        print("this is a DBN with", input_n_frames, "frames on the input layer")
        print("concatenating MFCC files") 
        all_mfcc = np.ndarray((0, dbn.rbm_layers[0].n_visible), dtype='float32')
        map_file_to_start_end = {}
        mfcc_file_name = 'tmp_allen_mfcc_' + str(int(input_n_frames)) + '.npy'
        map_mfcc_file_name = 'tmp_allen_map_file_to_start_end_' + str(int(input_n_frames)) + '.pickle'
        try:
            print("loading concat MFCC from pickled file")
            with open(mfcc_file_name) as concat_mfcc:
                all_mfcc = np.load(concat_mfcc)
            with open(map_mfcc_file_name) as map_mfcc:
                map_file_to_start_end = pickle.load(map_mfcc)
        except:
            for ind, mfcc_file in enumerate(list_of_mfcc_files):
                start = all_mfcc.shape[0]
                x = htkmfc.open(mfcc_file).getall()
                if input_n_frames > 1:
                    x = padding(input_n_frames, x)
                all_mfcc = np.append(all_mfcc, x, axis=0)
                map_file_to_start_end[mfcc_file] = (start, all_mfcc.shape[0])
                print("did", mfcc_file, "ind", ind)
            with open(mfcc_file_name, 'w') as concat_mfcc:
                np.save(concat_mfcc, all_mfcc)
            with open(map_mfcc_file_name, 'w') as map_mfcc:
                pickle.dump(map_file_to_start_end, map_mfcc)

        tmp_likelihoods = likelihoods_computer(all_mfcc)
        depth_1_likelihoods = depth_1_computer(all_mfcc)
        depth_2_likelihoods = depth_2_computer(all_mfcc)
        #depth_3_likelihoods = depth_1_computer(all_mfcc) TODO
        print(map_states_to_phones)
        print(dbn_phones_to_states)
        columns_remapping = [dbn_phones_to_states[map_states_to_phones[i]] for i in range(tmp_likelihoods.shape[1])]
        likelihoods = (tmp_likelihoods[:, columns_remapping],
            map_file_to_start_end)
        print("computed all likelihoods")
        #likelihoods = (tmp_likelihoods, map_file_to_start_end)
    else:
        all_mfcc = np.ndarray((0, 39), dtype='float32')
        map_file_to_start_end = {}
        mfcc_file_name = 'tmp_allen_mfcc_.npy'
        map_mfcc_file_name = 'tmp_allen_map_file_to_start_end_.pickle'
        try:
            print("loading concat MFCC from pickled file")
            with open(mfcc_file_name) as concat_mfcc:
                all_mfcc = np.load(concat_mfcc)
            with open(map_mfcc_file_name) as map_mfcc:
                map_file_to_start_end = pickle.load(map_mfcc)
        except:
            for ind, mfcc_file in enumerate(list_of_mfcc_files):
                start = all_mfcc.shape[0]
                x = htkmfc.open(mfcc_file).getall()
                all_mfcc = np.append(all_mfcc, x, axis=0)
                map_file_to_start_end[mfcc_file] = (start, all_mfcc.shape[0])
                print("did", mfcc_file, "ind", ind)
            with open(mfcc_file_name, 'w') as concat_mfcc:
                np.save(concat_mfcc, all_mfcc)
            with open(map_mfcc_file_name, 'w') as map_mfcc:
                pickle.dump(map_file_to_start_end, map_mfcc)
        likelihoods = (likelihoods_computer(all_mfcc), map_file_to_start_end)

    il = InnerLoop(likelihoods, map_states_to_phones, transitions, 
            depth_1_likelihoods=depth_1_likelihoods,
            depth_2_likelihoods=depth_2_likelihoods)
    list(map(il, list_of_mfcc_files))
    #n_processors = cpu_count()
    #p = Pool(n_processors)
    #print "launching", n_processors, "Viterbi"
    #p.map(il, list_of_mfcc_files)
    #from joblib import Parallel, delayed
    #Parallel(n_jobs=n_processors)(delayed(il)(i) for i in list_of_mfcc_files)
