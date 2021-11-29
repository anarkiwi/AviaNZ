"""
23/11/2021
Author: Virginia Listanti

This program implements the experiment pipeline for the IF extraction

This program is built to run on the CUDA machines

PIPELINE:
- Iterate over:
       * possible TFRs & co.
            - TFR: Short-time Fourier Transform
            - Post-processing: Reassigned, Multitapered
            - Frequency scale: Linear, Mel
            - Spectrogram Normalization: Log, Box-Cox, Sigmoid, PCEN

       * parameter optimization metric:
            - L2
            - Iatsenko (no pure-tone)
            - curve registration [note available at the moment]


For each Test:
    - Create dir (local Virginia) where to store the result metrics
    - Store TEST INFO: TFR  + parameter optimization metric
    - Navigate Dataset subdirectory (aka signal-type)

    * For each subdirectory in the dataset directory (aka signal-type):
        - create subdirectory in the test result directory
        - Find optimal parameters using optimization metric: window_lenght, incr, window_type
        - Store optimal paramters info
        - Evaluate & store as .csv Baseline metrics for "pure" signal
        - Initialize general metrics (for signal type): 1 column for each noise level
        - Navigate subdirectory with noise-level samples

        * For each noise level
            - initialize local metrics (1 column for each metric)
            - evaluate metrics for each samples ans store both in local and general
            - save local metrics in .csv

        - Save general metrics as .csv
        - Update Test id

Metrics we are going to measure:
    * Baseline metrics:
        - Signal-to-noise ratio
        - Renyi Entropy of the spectrogram

    * Metrics on IF extraction (between correct IF and extracted IF)
        - l2 norm
        - Iatsenko error
        - Geodetic distance

    * Metric on spectrogram inversion
        - SISDR (between signal obtained via spectrogram inversion and original signal without noise) &
                (between signal obtained via spectrogram inversion and original signal)
        - STOI  (between signal obtained via spectrogram inversion and original signal without noise) &
                (between signal obtained via spectrogram inversion and original signal)
        - IMED (Between spectrogram of inverted signal and original spectrogram without noise)
                (Between spectrogram of inverted signal and original spectrogram without noise)

"""

import SignalProc
import IF as IFreq
import numpy as np
from numpy.linalg import norm
#sfrom scipy.io import loadmat, savemat
import matplotlib.pyplot as plt
import os
from scipy import optimize
import scipy.special as spec
import wavio
import csv
import imed
import speechmetrics as sm
from fdasrsf.geodesic import geod_sphere

########################## Utility functions ###########################################################################
def Signal_to_noise_Ratio(signal, noise):
    # Signal-to-noise ratio
    # Handle the case with no noise as well
    if len(noise) == 0:
        snr = 0
    else:
        snr = 10 * np.log10((np.sum(signal** 2)/len(signal)) / (np.mean(noise ** 2)/len(noise)))
    return snr


def Renyi_Entropy(A, order=3):
    # Renyi entropy.
    # Default is order 3

    R_E = (1 / (1 - order)) * np.log2(np.sum(A ** order) / np.sum(A))
    return R_E


def Iatsenko_style(s1, s2):
    # This function implement error function as defined
    # in Iatsenko et al. IF paper
    # s1 is the reference signal
    try:
        error = np.mean((s1 - s2) ** 2) / np.mean((s1 - np.mean(s1)) ** 2)
    except:
        error=np.nan
    return error

def IMED_distance(A,B):
    # This function evaluate IMED distance between 2 matrix
    # 1) Rescale matrices to [0,1]
    # 2) call imed distance

    A2=(A-np.amin(A))/np.ptp(A)
    B2=(B-np.amin(B))/np.ptp(B)

    return imed.distance(A2,B2)

def Geodesic_curve_distance(x1, y1, x2, y2):
    """
    Code suggested by Arianna Salili-James
    This function computes the distance between two curves x and y using geodesic distance

    Input:
         - x1, y1 coordinates of the first curve
         - x2, y2 coordinates of the second curve
    """

    beta1 = np.column_stack([x1, y1]).T
    beta2 = np.column_stack([x2, y2]).T

    distance, _, _ = geod_sphere(np.array(beta1), np.array(beta2))

    return distance

def set_if_fun(signal_id,T):
    """
    Utility function to manage the instantaneous frequency function
    """
    if signal_id=="pure_tone":
        omega=2000
        if_fun = lambda t: omega * np.ones((np.shape(t)))

    elif signal_id=="exponential_downchirp":
        omega_1=500
        omega_0=2000
        alpha=(omega_1/omega_0)**(1/T)
        if_fun=lambda x: omega_0*alpha**x

    elif signal_id=="exponential_upchirp":
        omega_1=2000
        omega_0=500
        alpha=(omega_1/omega_0)**(1/T)
        if_fun=lambda x: omega_0*alpha**x

    elif signal_id=="linear_downchirp":
        omega_1=500
        omega_0=2000
        c=(omega_1-omega_0)/T
        if_fun=lambda x: omega_0+c*x

    elif signal_id=="linear_upchirp":
        omega_1=2000
        omega_0=500
        c=(omega_1-omega_0)/T
        if_fun=lambda x: omega_0+c*x

    else:
        print("ERROR SIGNAL ID NOT CONSISTENT WITH THE IF WE CAN HANDLE")
    return if_fun

def find_optimal_spec_IF_parameters(signal_path, save_dir, signal_id, spectrogram_type, freq_scale, norm_type, opt_metric):
    """
    This function find optimal parameters for the spectrogram and the frequency extraction algorithm in order
    to minimize the distance opt_metric between the extracted IF and the "original" ones

    Input:
        signal id
        save_dir directory where to save log and parameters
        inst_freq_fun: lambda function with instantaneous freqeuncy law
        Spectrogram_type
        freq_scale
        norm_type
        opt_metric

    Output
        window_length_opt
        incr_opt
        window_type_opt
        alpha_opt
        beta_opt
    """

    # Spectrogram parameters
    win = np.array([32, 64, 128, 256, 1024, 2048, 4096])
    hop_perc = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
    win_type = ['Hann', 'Parzen', 'Welch', 'Hamming', 'Blackman', 'BlackmanHarris']

    # If Extraction parameters:
    alpha_list = np.array([0, 0.25, 0.5, 1, 2, 4, 6, 8, 10, 15, 20])
    beta_list = np.array([0, 0.25, 0.5, 1, 2, 4, 6, 8, 10, 15, 20])

    opt = np.Inf
    opt_param = {"window_lenght": [], "hop": [], "window_type": [], "alpha": [], "beta": []}

    # store values into .csv file
    # fieldnames=['window_width','incr','n. columns', 'measure']
    fieldnames = ['window_width', 'incr', 'window type', 'alpha', 'beta','spec dim', 'measure']
    csv_filename = save_dir+ '/find_optimal_parameters_log.csv'
    with open(csv_filename, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

    for win_len in win:
        for hop in hop_perc:
            for window_type in win_type:
                for alpha in alpha_list:
                    for beta in beta_list:

                        window_width = int(win_len)
                        incr = int(win_len * hop)
                        print(window_width, incr)
                        IF = IFreq.IF(method=2, pars=[alpha, beta])
                        sp = SignalProc.SignalProc(window_width, incr)
                        sp.readWav(signal_path)
                        fs = sp.sampleRate

                        TFR = sp.spectrogram(window_width, incr, window_type, sgType=spectrogram_type, sgScale=freq_scale)
                        TFR = TFR.T
                        print("spec dim", np.shape(TFR))

                        if freq_scale=="Linear":
                            fstep = (fs / 2) / np.shape(TFR)[0]
                            freqarr = np.arange(fstep, fs / 2 + fstep, fstep)
                        else:
                            # #mel freq axis
                            nfilters=40
                            freqarr = np.linspace(sp.convertHztoMel(0), sp.convertHztoMel(fs/2), nfilters + 1)
                            freqarr=freqarr[1:]
                        # fstep=np.mean(np.diff(freqarr))

                        wopt = [fs, window_width]  # this neeeds review
                        tfsupp, _, _ = IF.ecurve(TFR, freqarr, wopt)

                        T=sp.fileLength/fs
                        inst_freq_fun = set_if_fun(signal_id, T)
                        inst_freq = inst_freq_fun(np.linspace(0, T, np.shape(tfsupp[0, :])[0]))

                        if opt_metric=="L2":
                            measure2check = norm(tfsupp[0, :] - inst_freq, ord=2) / (np.shape(TFR)[0] * np.shape(TFR)[1])
                        elif opt_metric=="Iatsenko":
                            measure2check = Iatsenko_style(inst_freq, tfsupp[0,:])
                        else:
                            t_support = np.linspace(0, T, np.shape(tfsupp[0, :])[0])
                            measure2check= Geodesic_curve_distance(t_support,tfsupp[0,:], t_support, inst_freq)

                        with open(csv_filename, 'a', newline='') as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                            writer.writerow(
                                {'window_width': window_width, 'incr': incr, 'spec dim': np.shape(TFR)[0] * np.shape(TFR)[1],
                                 'measure': measure2check})

                        if measure2check < opt:
                            print("optimal parameters updated:", opt_param)
                            print(norm(tfsupp[0, :] - inst_freq, ord=2))
                            opt = measure2check
                            opt_param["win_len"] = window_width
                            opt_param["hop"] = incr

            del TFR, fstep, freqarr, wopt, tfsupp, window_width, incr, sp, IF, measure2check

    print("optimal parameters \n", opt_param)
    window_width = opt_param["win_len"]
    incr = opt_param["hop"]
    return window_length_opt, incr_opt, window_type_opt, alpha_opt, beta_opt


def save_test_info(file_path, spec_type, scale, norm_type, opt_metric):
    """
    This function stores TFR info into a .txt file
    """

########################################################################################################################
########################################################   MAIN ########################################################
########################################################################################################################


# directory where to find test dataset files
dataset_dir = "/media/smb-vuwstocoissrin1.vuw.ac.nz-ECS_acoustic_03/Virginia_IF_experiment"
# directory to store test result
main_results_dir = '/am/state-opera/home1/listanvirg/Documents/IF_experiment_Results'

# signals list
signals_list = os.listdir(dataset_dir)

# TFR options
# sgtypes
spectrogram_types=["Standard", "Reassigned", "Multi-tapered"]
# sgscale
freq_scales=['Linear','Mel Frequency']
# spectrogram normalization functions
spec_normalizations=["Standard", "Log", "Box-Cox", "Sigmoid", "PCEN"]
# optimization metrics
optimization_metrics=['L2', 'Iatsenko', 'Curve_registration']

# Inizialization
Test_id=0


#start loop

for spec_type in spectrogram_types:
    # loop over different spectrogrma types

    for scale in freq_scales:
        #loop over possible scales

        for norm_type in spec_normalizations:
            #loop over spectrogram normalizations techniques

            for opt_metric in optimization_metrics:
                #loop over optimization metrics
                print("Starting test:"  , Test_id)
                #create test result directory
                test_result_dir=main_results_dir+'/Test'+Test_id

                if not os.path.lexists(test_result_dir):
                    os.mkdir(test_result_dir)

                #store Test info
                test_info_file_path=test_result_dir+'TFR_info.txt'
                save_test_info(test_info_file_path, spec_type, scale, norm_type, opt_metric)

                for signal_id in os.listdir(dataset_dir):
                    #ADD CHECK TO SKIP IF OPT_METRIC==IATSENKO
                    # looping over signal_directories
                    folder_path=dataset_dir+'/'+signal_id
                    print("Analysing folder: ", folder_path)
                    #create test_dir for signal type
                    test_result_subfolder=test_result_dir+'/'+signal_id
                    if not os.path.exists(test_result_subfolder):
                        os.mkdir(test_result_subfolder)

                    #inst.frequency law
                    pure_signal_path=folder_path+'/Base_Dataset_2/'+signal_id+'00.wav'
                    #create path for storing test parameters
                    save_test_parameters_path=test_result_subfolder+"/Test_parameters.txt"
                    window_length, incr, window_type, alpha, beta = find_optimal_spec_IF_parameters(pure_signal_path, signal_id,spec_type, scale,
                                                                                       norm_type, opt_metric)