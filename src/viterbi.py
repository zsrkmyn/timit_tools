import numpy as np
from numpy import linalg
import functools
import sys, math
import pickle
from collections import defaultdict, deque
import htkmfc
import itertools
from multiprocessing import Pool, cpu_count
from functools import reduce

usage = """
python viterbi.py OUTPUT[.mlf] INPUT_SCP INPUT_HMM  
        [--p INSERTION_PENALTY] [--s SCALE_FACTOR] 
        [--b INPUT_LM] [--w WDNET] [--ub UNI&BIGRAM_LM]

Exclusive uses of these options:
    --b followed by an HTK bigram file (ARPA-MIT LL or matrix bigram, see code)
        /!\ A bigram LM will only work if there are sentences start/end
            (the default symbols are !ENTER/!EXIT)
    --w followed by a wordnet (bigram only)
    --ub followed by a pickled bigram file (apply src/produce_LM.py to a MLF)
"""

VERBOSE = False
UNIGRAMS_ONLY = False # says if we use only unigrams when we have _our_ bigrams
MATRIX_BIGRAM = True # is the bigram file format a matrix? (ARPA-MIT if False)
THRESHOLD_BIGRAMS = -10.0 # log10 min proba for a bigram to not be backed-off
SCALE_FACTOR = 1.0 # importance of the LM w.r.t. the acoustics
INSERTION_PENALTY = 2.5 # penalty of inserting a new phone (in the Viterbi)
epsilon = 1E-6 # degree of precision for floating (0.0-1.0 probas) operations
epsilon_log = 1E-80 # to add for logs

class Phone:
    def __init__(self, phn_id, phn):
        self.phn_id = phn_id
        self.phn = phn
        self.to_ind = []

    def update(self, indice):
        self.to_ind.append(indice)

    def __repr__(self):
        return self.phn + ": " + str(self.phn_id) + '\n' + str(self.to_ind)


def clean(s):
    return s.strip().rstrip('\n')


def eval_gauss_mixt(v, gmixt):
    assert(len(gmixt[0]) == gmixt[1].shape[0] == gmixt[2].shape[0])
    def eval_gauss_comp(mix_comp): # closure
        pi_k, mu_k, sigma_k_inv = mix_comp
        return pi_k * math.exp(-0.5 * np.dot((v - mu_k).T, 
                    np.dot(sigma_k_inv, v - mu_k)))
    return reduce(lambda x, y: x + y, list(map(eval_gauss_comp, 
        zip(gmixt[0], gmixt[1], gmixt[2]))))


def precompute_det_inv(gmms):
    # /!\ iteration order is important, this gives us:
    ret = []
    for _, gm in gmms.items():
        for gm_st in gm:
            pi_k = []
            mu_k = []
            inv_sqrt_det_sigma = []
            inv_sigma = []
            for component in gm_st:
                pi_k.append(component[0])
                mu_k.append(component[1])
                sigma2_k = component[2]
                inv_sqrt_det_sigma.append(1.0 / np.sqrt(linalg.det(2 * np.pi * np.diag(sigma2_k))))
                inv_sigma.append(1.0 / np.array(sigma2_k))
                assert((inv_sigma[-1] == np.diag(linalg.inv(np.diag(sigma2_k)))).all())
            ret.append((np.array(pi_k) * np.array(inv_sqrt_det_sigma), 
                    np.array(mu_k).T, 
                    np.array(inv_sigma).T))
    return ret


def compute_likelihoods(gmms_, mat):
    """ compute the log-likelihoods of each states i according to the Gaussian 
    mixture in gmms_[i], for each line of mat (input data) """
    ret = np.ndarray((mat.shape[0], len(gmms_)), dtype="float64")
    ret[:] = 0.0
    for state_id, mixture in enumerate(gmms_):
        pis, mus, inv_sigmas = mixture
        # N_mixtures = len(pis) = mus.shape[1] = inv_sigmas.shape[1]
        # N_features = mus.shape[0] = inv_sigmas.shape[0]
        assert(pis.shape[0] == mus.shape[1])
        assert(pis.shape[0] == inv_sigmas.shape[1])
        x_minus_mus = np.ndarray((mat.shape[0], mus.shape[0], mus.shape[1]))
        x_minus_mus.T[:,] = mat.T
        x_minus_mus -= mus
        x_minus_mus = x_minus_mus ** 2
        x_minus_mus *= inv_sigmas
        components = np.exp(-0.5 * x_minus_mus.sum(axis=1))
        ret[:, state_id] = np.log(np.dot(components, pis))
    return ret


def padding(nframes, x):
    """ padding with (nframes-1)/2 frames before & after for *.mfc mat x"""
    ba = (nframes - 1) / 2
    x_f = np.zeros((x.shape[0], nframes * x.shape[1]), dtype='float32')
    for i in range(x.shape[0]):
        x_f[i] = np.pad(x[max(0, i-ba):i+ba+1].flatten(),
                (max(0, (ba-i) * x.shape[1]), max(0, 
                    ((i+ba+1) - x.shape[0]) * x.shape[1])), 
                'constant', constant_values=(0,0))
    return x_f


def phones_mapping(gmms):
    map_states_to_phones = {}
    i = 0
    for phn, gm in gmms.items():
        st_id = 2
        for gm_st in gm:
            map_states_to_phones[i] = phn + "[" + str(st_id) + "]"
            i += 1
            st_id += 1
    return map_states_to_phones


def string_mlf(map_states_to_phones, states, phones_only=False):
    s = []
    previous_phone = ''
    previous_state = '' 
    total_prob = 0.0
    n_timesteps_collapsed = 0
    tmp_s = ''
    for state, prob in states: 
        state_s = map_states_to_phones[state]
        phone = state_s.split('[')[0]
        # TODO correct timings with forced alignment
        if phone != previous_phone:
            tmp_s += phone + ' '
            previous_phone = phone
            total_prob = prob # useless as we do not output probs
            n_timesteps_collapsed = 1 # same as above comment
        if not phones_only and state_s != previous_state:
            tmp_s += state_s + ' '
            if len(s):
                s[-1] = s[-1] + str(total_prob) + ' ' + str(
                        total_prob/n_timesteps_collapsed) # divide to correct
            previous_state = state_s
            total_prob = prob
            n_timesteps_collapsed = 1
        else:
            total_prob += prob
            n_timesteps_collapsed += 1
        if len(tmp_s):
            s.append(tmp_s)
            tmp_s = ''
    if not phones_only:
        s[-1] = s[-1] + str(total_prob) + ' ' + str(
                total_prob/n_timesteps_collapsed) # divide to correct
    s.append('')
    return '\n'.join(s)


def viterbi(likelihoods, transitions, map_states_to_phones, 
        using_bigram=False):
    """ This function applies Viterbi on the likelihoods already computed """
    starting_state = None
    ending_state = None
    for state, phone in map_states_to_phones.items():
        if using_bigram:
            if phone == '!ENTER[2]' or phone == 'h#[2]': # hardcoded TODO remove
                starting_state = state
            if phone == '!EXIT[4]' or phone == 'h#[4]': # hardcoded TODO remove
                ending_state = state
    posteriors = np.ndarray((likelihoods.shape[0], likelihoods.shape[1]))
    posteriors[:] = -1000000.0 # log
    posteriors[0] = likelihoods[0] # log
    backpointers = np.ndarray((likelihoods.shape[0]-1, likelihoods.shape[1]), 
            dtype=int)
    backpointers[:] = -1
    if using_bigram:
        nonnulls = [starting_state]
    else:
        nonnulls = [jj for jj, val in enumerate(posteriors[0]) if val > -1000000.0] 
    log_transitions = transitions[1] # log,

    # Main viterbi loop, try with native code if possible
    try:
        from scipy import weave
        from scipy.weave import converters
        px = likelihoods.shape[0]
        py = likelihoods.shape[1]
        code_c = """
                #line 180 "viterbi.py" (FOR DEBUG)
                for (int i=1; i < px; ++i) { 
                    for (int j=0; j < py; ++j) {
                        float max_ = -100000000000.0;
                        int max_ind = -2;
                        for (int k=0; k < py; ++k) {
                            if (likelihoods(i-1,k) < max_ || log_transitions(k,j) < max_)
                                continue;
                            float tmp_prob = posteriors(i-1,k) + log_transitions(k,j);
                            if (tmp_prob > max_) {
                                max_ = tmp_prob;
                                max_ind = k;
                            }
                        }
                        posteriors(i,j) = max_ + likelihoods(i,j);
                        backpointers(i-1,j) = max_ind;
                    }
                }
                """
        err = weave.inline(code_c,
                ['px', 'py', 'log_transitions', 
                    'likelihoods', 'posteriors', 'backpointers'],
                type_converters=converters.blitz,
                compiler = 'gcc')
    except:
        for i in range(1, likelihoods.shape[0]):
            for j in range(likelihoods.shape[1]):
                max_ = -1000000000000.0 # log
                max_ind = -2
                for k in nonnulls:
                    #if transitions[1][k][j] == 0.0:
                    if log_transitions[k][j] < max_:
                        continue
                    tmp_prob = posteriors[i-1][k] + log_transitions[k][j] # log
                    if tmp_prob > max_:
                        max_ = tmp_prob
                        max_ind = k
                posteriors[i][j] = max_ + likelihoods[i][j] # log
                backpointers[i-1][j] = max_ind
            nonnulls = [jj for jj, val in enumerate(likelihoods[i]) if val > -1000000.0] # log
            if len(nonnulls) == 0:
                print(">>>>>>>>> NONNULLS IS EMPTY", i, likelihoods.shape[0], file=sys.stderr)

    if using_bigram:
        states = deque([(ending_state, posteriors[likelihoods.shape[0]-1][ending_state])])
    else:
        states = deque([(posteriors[likelihoods.shape[0]-1].argmax(), posteriors[likelihoods.shape[0]-1].max())])
    for i in range(likelihoods.shape[0] - 2, -1, -1):
        states.appendleft((backpointers[i][states[0][0]], posteriors[i][backpointers[i][states[0][0]]]))
        #states.appendleft((posteriors[i].argmax(), posteriors[i].max()))

    #import scipy.io
    #scipy.io.savemat('log_likelihoods.mat', mdict={
        #'log_likelihoods': likelihoods,
        #'log_transitions': log_transitions,
    #    'best_parse_state_logProb_tuple': states})
    #sys.exit(0)
    return states, posteriors


def parse_wdnet(trans, iwdnf):
    """ puts transition probabilities with bigram LM generated wdnet:
        HBuild -m bigramLM dict wdnetbigram
    """
    indices_to_phones = {}
    n_phones = 0
    bp = {} # buffer prob, 
    # filled before the first time that we modify a final state trans. proba
    for line in iwdnf:
        line = line.rstrip('\n').split()
        ident = line[0][0:2]
        if ident == "N=":
            n_phones = int(line[0].split('=')[1])
        elif ident == "I=":
            indices_to_phones[line[0].split('=')[1]] = line[1].split('=')[1]
        elif ident == "J=":
            phn1 = indices_to_phones[line[1].split('=')[1]]
            phn2 = indices_to_phones[line[2].split('=')[1]]
            log_prob = float(line[3].split('=')[1])
            phone1 = trans[0][phn1]
            phone2 = trans[0][phn2]
            bp[phn1] = bp.get(phn1, 1.0 - trans[1][phone1.to_ind[-1]].sum(0))
            trans[1][phone1.to_ind[-1]][phone2.to_ind[0]] = bp[phn1] * np.exp(log_prob)

    assert(n_phones == len(indices_to_phones))
    for phn1, phone1 in trans[0].items():
        trans[1][phone1.to_ind[-1]] /= trans[1][phone1.to_ind[-1]].sum(0) # TODO remove (that's because of !EXIT)
        #print trans[1][phone1.to_ind[-1]].sum(0)
        assert(1.0 - epsilon < trans[1][phone1.to_ind[-1]].sum(0) < 1.0 + epsilon) # make sure we normalized our probs
    np.save(open('wdnet_transitions.npy', 'w'), trans[1])
    return trans


def initialize_transitions(trans, unibi=None, unigrams_only=False):
    """ takes the transition matrix only inter HMMs and give uniform or unigram
    or bigram probabilities of transitions between each last and first state """
    uni = None
    bi = None
    if unibi != None:
        uni, bi, discounts = pickle.load(unibi)
    for phn1, phone1 in trans[0].items():
        if phn1 == '!EXIT':                                                                  # TODO remove
            trans[1][phone1.to_ind[-1]][:] = 0.0 # no trans to anything else                 # TODO remove
            trans[1][phone1.to_ind[-1]][phone1.to_ind[-1]] = 1.0 # no trans to anything else # TODO remove
            continue                                                                         # TODO remove
        already_in_prob = trans[1][phone1.to_ind[-1]][phone1.to_ind[-1]]
        to_distribute = (1.0 - already_in_prob) 
        value = to_distribute / (len(trans[0]) - 1) # - !ENTER                               # TODO remove
        for phn2, phone2 in trans[0].items():
            if phn2 == '!ENTER':                                                             # TODO remove
                trans[1][phone1.to_ind[-1]][phone2.to_ind[0]] = 0.0 # no trans to !ENTER     # TODO remove
                continue                                                                     # TODO remove
            if bi != None: # bigrams
                if not unigrams_only and phn1 in bi: # we use the full bigrams!
                    if phn2 in bi[phn1]:
                        value = to_distribute * bi[phn1][phn2]
                    else:
                        value = to_distribute * discounts[phn1] * uni[phn1]
                else: # phn1 not in bi means it's _always_ the last phone
                    value = to_distribute * uni[phn1]
            trans[1][phone1.to_ind[-1]][phone2.to_ind[0]] = value
        #print trans[1][phone1.to_ind[-1]].sum(0)
        trans[1][phone1.to_ind[-1]] /= trans[1][phone1.to_ind[-1]].sum(0) # we need this because of approximations
        assert(1.0 - epsilon < trans[1][phone1.to_ind[-1]].sum(0) < 1.0 + epsilon) # make sure we normalized our probs
    return trans


def penalty_scale(trans, insertion_penalty=0.0, scale_factor=1.0):
    """ 
     * transforms the transition probabilities matrix in logs probabilities
     * adds the insertion penalty
     * multiplies the phones transitions by the grammar scale factor
    """
    log_trans = np.log(trans[1] + epsilon_log)
    for phn1, phone1 in trans[0].items():
        for phn2, phone2 in trans[0].items():
            log_trans[phone1.to_ind[-1]][phone2.to_ind[0]] *= scale_factor
            log_trans[phone1.to_ind[-1]][phone2.to_ind[0]] -= insertion_penalty
    print("Insertion penalty:", insertion_penalty, "and grammar scale factor:", scale_factor)
    return (trans[0], log_trans)


def parse_lm_matrix(trans, f):
    import re
    l = [re.sub('[ ]+', ' ', line.rstrip('\n').replace('  ', ' ')) 
            for line in f]
    ll = [] # split lines
    p = {} # p[A][B] = P(B|A), probability
    phones = [] # order
    for line in l:
        tmp = line.split()
        p[tmp[0]] = {}
        ll.append(tmp[1:])
        phones.append(tmp[0])
    for i, probs in enumerate(ll):
        j = 0
        tmp_probs = []
        for j, prob in enumerate(probs):
            if '*' in prob:
                pr, k = prob.split('*')
                for kk in range(int(k)):
                    tmp_probs.append(pr)
            else:
                tmp_probs.append(prob)
        assert(len(tmp_probs) == len(phones) == len(list(p.keys())))
        for j, prob in enumerate(tmp_probs):
            p[phones[i]][phones[j]] = float(prob)

    for phn1, d in p.items():
        phone1 = trans[0][phn1]
        buffer_prob = 1.0 - trans[1][phone1.to_ind[-1]].sum(0)
        assert(buffer_prob != 0.0) # you would never go out of this phone (/!\ !EXIT)
        for phn2, prob in d.items():
            # transition from phn1 to phn2
            phone2 = trans[0][phn2]
            trans[1][phone1.to_ind[-1]][phone2.to_ind[0]] = buffer_prob * prob
        assert(1.0 - epsilon < trans[1][phone1.to_ind[-1]].sum(0) < 1.0 + epsilon) # make sure we have normalized probs
    np.save(open('matrix_transitions.npy', 'w'), trans[1])
    return trans


def parse_lm(trans, f):
    """ parse ARPA MIT-LL backed-off bigrams in f """
    p_1grams = {}
    b_1grams = {}
    p_2grams = defaultdict(lambda: {}) # p_2grams[A][B] = log10 P(B|A)
    # parse the file to fill the above dicts
    parsing1grams = False
    parsing2grams = False
    parsed1grams = 0
    parsed2grams = 0
    for line in f:
        if clean(line) == "":
            continue
        if "1-grams" in line:
            parsing1grams = True
        elif "2-grams" in line:
            parsing1grams = False
            parsing2grams = True
        elif "end" == line[1:4]:
            break
        elif parsing1grams: 
            l = clean(line).split()
            p_1grams[l[1]] = float(l[0]) # log10 prob
            if len(l) > 2:
                b_1grams[l[1]] = float(l[2]) # log10 prob
            else:
                b_1grams[l[1]] = -10000000.0 # guess that's low enough
            parsed1grams += 1
        elif parsing2grams:
            l = clean(line).split()
            if len(l) != 3:
                print("bad language model file format", file=sys.stderr)
                sys.exit(-1)
            p_2grams[l[1]][l[2]] = float(l[0]) # log10 prob, already discounted
            parsed2grams += 1
    print("Parsed", parsed1grams, "1-grams, and", parsed2grams, "2-grams")

    # do the backed-off probs for p_2grams[phn1][phn2] = P(phn2|phn1)
#    for phn1, d in p_2grams.iteritems():
#        s = 0.0
#        for phn2, log_prob in d.iteritems():
#            # j follows i, p(j)*b(i)
#            if log_prob < p_1grams[phn2] + b_1grams[phn1] \
#                    or log_prob < THRESHOLD_BIGRAMS:
#                p_2grams[phn1][phn2] = p_1grams[phn2] + b_1grams[phn1]
#            s += 10 ** p_2grams[phn1][phn2]
#        s = math.log10(s)
#        for phn2, log_prob in d.iteritems():
#            p_2grams[phn1][phn2] = log_prob - s

    # edit the trans[1] matrix with the backed-off probs,
    # could do in the above "backed-off probs" loop 
    # I but prefer to keep it separated
    for phn1, b1_1g in b_1grams.items():
    #for phn1, d in p_2grams.iteritems():
        phone1 = trans[0][phn1]
        buffer_prob = 1.0 - trans[1][phone1.to_ind[-1]].sum(0)
        assert(buffer_prob != 0.0) # you would never go out of this phone (/!\ !EXIT)
        for phn2, p2_1g in p_1grams.items():
        #for phn2, log_prob in d.iteritems():
            # transition from phn1 to phn2
            phone2 = trans[0][phn2]
            log_prob = p2_1g + b1_1g
            if phn1 in p_2grams and phn2 in p_2grams[phn1]:
                log_prob = p_2grams[phn1][phn2]
            trans[1][phone1.to_ind[-1]][phone2.to_ind[0]] = buffer_prob * (10 ** log_prob)
        trans[1][phone1.to_ind[-1]] /= trans[1][phone1.to_ind[-1]].sum(0) # TODO remove (that's because of !EXIT)
        #print trans[1][phone1.to_ind[-1]].sum(0)
        assert(1.0 - epsilon < trans[1][phone1.to_ind[-1]].sum(0) < 1.0 + epsilon) # make sure we normalized our probs
    np.save(open('ARPA-MIT_transitions.npy', 'w'), trans[1])
    return trans


def parse_hmm(f):
    """ parse HTK HMMdefs (chapter 7 of the HTK book) in f """
    l = f.readlines()
    n_phones = 0
    n_states_tot = 0
    for line in l:
        # GCONST = ln((2*pi)^n det(sigma)) == ln(det(2*pi*sigma))
        if '~h' in line:
            n_phones += 1
        elif '<NUMSTATES>' in line:
            n_states_tot += int(line.strip().split()[1]) - 2 
            # we remove init/end states: eg. 5 means 3 states once connected
    transitions = ({}, np.ndarray((n_states_tot, n_states_tot), 
        dtype='float64'))
    # transitions = ( t[phn] = Phone,
    #                               | phn1_s1, phn1_s2, phn1_s3, phn2_s1|
    #                     ----------|-----------------------------------|
    #                     | phn1_s1 | proba  , proba_2, proba  , proba  |
    #                     | phn1_s2 | proba  , proba  , proba  , proba  |
    #                     | phn1_s3 | proba  , proba  , proba  , proba  |
    #                     | phn2_s1 | proba  , proba  , proba  , proba  |
    #                     -----------------------------------------------  )
    #             with proba_2 marking the transition from phn1_s1 to phn_s2
    gmms = {}
    #                 <---  mix. comp.  --->
    # gmms[phn] = [ [ [pi_k, mu_k, sigma2_k] , ...] , ...]
    #               <----------  state  ---------->
    # gmms[phn] is a list of states, which are a list of Gaussian mixtures 
    # components, which are a list of weight (float) followed by means (vec) 
    # and covar (vec, circular (i.e. diagonal covar matrix) covar)
    phn = ""
    phn_id = -1
    current_states_numbers = 0
    for i, line in enumerate(l):
        if '~h' in line:
            phn = clean(line).split()[1].strip('"')
            phn_id += 1
            gmms[phn] = []
        elif '<STATE>' in line:
            gmms[phn].append([])
        elif '<MIXTURE>' in line:
            gmms[phn][-1].append([float(clean(line).split()[2])])
        elif '<MEAN>' in line or '<VARIANCE>' in line:
            if not len(gmms[phn][-1]):
                gmms[phn][-1].append([1.0])
            gmms[phn][-1][-1].append(np.array(list(map(float, 
                clean(l[i+1]).split())), dtype='float64'))
        elif '<TRANSP>' in line:
            n_st = int(clean(line).split()[1]) - 2  # we also remove init/end
            transitions[0][phn] = Phone(phn_id, phn)
            for j in range(n_st):
                transitions[0][phn].update(current_states_numbers + j)
                transitions[1][current_states_numbers + j] = \
                    [0.0 for tmp_k in range(current_states_numbers)] + \
                    list(map(float, clean(l[i + j + 2]).split()[1:-1])) + \
                    [0.0 for tmp_k in range(n_states_tot
                        - current_states_numbers - n_st)]
            current_states_numbers += n_st
    assert(n_states_tot == current_states_numbers)
    #print gmms["!EXIT"][0][0][0] # pi_k of state 0 and mixture comp. 0
    #print gmms["!EXIT"][0][0][1] # mu_k
    #print gmms["!EXIT"][0][0][2] # sigma2_k
    #print gmms["eng"][0][0][0] # pi_k of state 0 and mixture comp. 0
    #print gmms["eng"][0][0][1] # mu_k
    #print gmms["eng"][0][0][2] # sigma2_k
    #print transitions[0].keys() # phones
    #print transitions[0]["!EXIT"] # !EXIT phn_id = 61
    #print transitions[1] # all the transitions
    #print transitions[1][transitions[0]['aa'].to_ind[2]]
    return n_states_tot, transitions, gmms


class InnerLoop(object): # to circumvent pickling pbms w/ multiprocessing.map
    def __init__(self, comp_likelihoods, map_states_to_phones, transitions,
            using_bigram=False):
        self.comp_likelihoods = comp_likelihoods
        self.map_states_to_phones = map_states_to_phones
        self.transitions = transitions
        self.using_bigram = using_bigram
    def __call__(self, line):
        cline = clean(line)
        if VERBOSE:
            print(cline)
        likelihoods = self.comp_likelihoods(htkmfc.open(cline).getall())
        s = '"' + cline[:-3] + 'rec"\n' + \
                string_mlf(self.map_states_to_phones,
                        viterbi(likelihoods, self.transitions, 
                            self.map_states_to_phones,
                            using_bigram=self.using_bigram)[0],
                        phones_only=True) + '.\n'
        return s


def process(ofname, iscpfname, ihmmfname, 
        ilmfname=None, iwdnetfname=None, unibifname=None):

    with open(ihmmfname) as ihmmf:
        n_states, transitions, gmms = parse_hmm(ihmmf)

    gmms_ = precompute_det_inv(gmms)
    #gmms_ = [gm_st for _, gm in gmms.iteritems() for gm_st in gm]
    map_states_to_phones = phones_mapping(gmms)
    likelihoods_computer = functools.partial(compute_likelihoods, gmms_)

    if iwdnetfname != None:
        with open(iwdnetfname) as iwdnf:
            transitions = parse_wdnet(transitions, iwdnf) # parse wordnet
    elif ilmfname != None:
        with open(ilmfname) as ilmf:
            if MATRIX_BIGRAM:
                transitions = parse_lm_matrix(transitions, ilmf) # parse bigram LM in matrix format in ilmf
            else:
                transitions = parse_lm(transitions, ilmf) # parse bigram LM in ARPA-MIT in ilmf
    elif unibifname != None: # our own unigram and bigram counts,
                             # c.f. src/produce_LM.py
        with open(unibifname) as ubf:
            transitions = initialize_transitions(transitions, ubf, 
                    unigrams_only=UNIGRAMS_ONLY)
    else:
        # uniform transitions between phones
        transitions = initialize_transitions(transitions)
    transitions = penalty_scale(transitions, 
            insertion_penalty=INSERTION_PENALTY, scale_factor=SCALE_FACTOR)

    dummy = np.ndarray((2,2)) # to force only 1 compile of Viterbi's C
    viterbi(dummy, [None, dummy], {}) # also for this compile's debug purposes

    list_mlf_string = []
    with open(iscpfname) as iscpf:
        il = InnerLoop(likelihoods_computer, 
                map_states_to_phones, transitions,
                using_bigram=(ilmfname != None 
                    or iwdnetfname != None 
                    or unibifname != None))
        p = Pool(cpu_count())
        list_mlf_string = p.map(il, iscpf)
    with open(ofname, 'w') as of:
        of.write('#!MLF!#\n')
        for line in list_mlf_string:
            of.write(line)


if __name__ == "__main__":
    if len(sys.argv) > 3:
        if '--help' in sys.argv:
            print(usage)
            sys.exit(0)
        args = dict(enumerate(sys.argv))
        options = [ind_x for ind_x in enumerate(sys.argv) if '--' in ind_x[1][0:2]]
        input_unibi_fname = None # my bigram LM
        input_lm_fname = None # HStats bigram LMs (either matrix of ARPA-MIT)
        input_wdnet_fname = None # HTK's wdnet (with bigram probas)
        if len(options): # we have options
            for ind, option in options:
                args.pop(ind)
                if option == '--verbose':
                    VERBOSE = True
                if option == '--p':
                    INSERTION_PENALTY = float(args[ind+1])
                    args.pop(ind+1)
                if option == '--s':
                    SCALE_FACTOR = float(args[ind+1])
                    args.pop(ind+1)
                if option == '--ub':
                    input_unibi_fname = args[ind+1]
                    args.pop(ind+1)
                    print("initialize the transitions between phones with the discounted bigram lm", input_unibi_fname) 
                if option == '--b':
                    input_lm_fname = args[ind+1]
                    args.pop(ind+1)
                    print("initialize the transitions between phones with the bigram lm", input_lm_fname)
                if option == '--w':
                    input_wdnet_fname = args[ind+1]
                    args.pop(ind+1)
                    print("initialize the transitions between phones with the wordnet", input_wdnet_fname)
                    print("WILL IGNORE LANGUAGE MODELS!")
        else:
            print("initialize the transitions between phones uniformly")
        output_fname = list(args.values())[1]
        input_scp_fname = list(args.values())[2]
        input_hmm_fname = list(args.values())[3]
        process(output_fname, input_scp_fname, 
                input_hmm_fname, input_lm_fname, 
                input_wdnet_fname, input_unibi_fname)
    else:
        print(usage)
        sys.exit(-1)
