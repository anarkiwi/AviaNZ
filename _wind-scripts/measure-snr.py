# Script for calculating the SNR of the mixed (and denoised) sound files

set -e
import librosa
import numpy as np
import os
import speechmetrics
import csv

# set appropriately:
ROOTDIR = "/home/julius/Documents/kiwis/wind/deposited/denoising/"
# (output will be stored to the same ROOTDIR as well)
SIGDIR = os.path.join(ROOTDIR, "signal/")

def snr(f1, f2):
    wav1, _ = librosa.load(f1, sr=None)
    wav2, _ = librosa.load(f2, sr=None)
    wav1 = wav1/np.max(wav1)
    wav2 = wav2/np.max(wav2)
    Es = np.sum(np.power(wav2, 2))
    En = np.sum(np.power(wav2-wav1, 2))
    return Es/En

# load all relative metrics from the speechmetrics package
metrics = speechmetrics.load(['bsseval', 'stoi', 'sisdr'], window=None)

# tables for looking up the original signal files based on number
cleanf_lookup_richss = {"1": "ZA_20180922_180719.wav",
        "2": "ZA_20180922_181919.wav", "3": "ZA_20180923_051735.wav",
        "4": "ZA_20180923_052135.wav", "5": "ZI_20180915_181500.wav",
        "6": "ZI_20180915_182700.wav"}
cleanf_lookup_handheld = {"1": "nXC101551.wav",
        "2": "nXC121079.wav", "3": "nXC30184.wav", "4": "nXC409363.wav",
        "5": "nXC492916.wav", "6": "nXC561864.wav"}

# main loop
def get_measures(indir, statfile):
    print("Processing dir", indir)
    score_list = []
    os.chdir(indir)

    for subdir in ["handheld", "richss"]:
        for noisyf in os.listdir(subdir):
            # parse some file info
            mixingsnr = noisyf[3]  # will store 1/2/3, not the actual SNR
            noisyf_string = noisyf[:-4]
            signum = noisyf[-5]
            noisenum = noisyf[10]
            if subdir=="handheld":
                cleanf = cleanf_lookup_handheld[signum]
            elif subdir=="richss":
                cleanf = cleanf_lookup_richss[signum]
            cleanf_string = cleanf[:-4]

            noisyf = os.path.join(subdir, noisyf)
            print("found file", noisyf)
            cleanf = os.path.join(SIGDIR, subdir, cleanf)
            print("corresponding clean file is", cleanf)

            # calculate the actual metrics
            scores = metrics(noisyf, cleanf)
            scores["snr"] = snr(noisyf, cleanf)
            scores["sdr"] = scores["sdr"][0][0]  # they need unnesting
            scores["isr"] = scores["isr"][0][0]
            scores["sar"] = scores["sar"][0][0]
            print(scores)

            # add source info
            scores["cleanf"] = cleanf_string
            scores["noisyf"] = noisyf_string
            scores["mixingsnr"] = mixingsnr
            scores["sigtype"] = subdir
            scores["noisetype"] = noisenum
            score_list.append(scores)

    # export csv
    print("Saving output to", statfile)
    with open(statfile, 'w', encoding='utf8', newline='') as csvf:
        fwriter = csv.DictWriter(csvf, fieldnames=score_list[0].keys(), dialect='unix')
        fwriter.writeheader()
        fwriter.writerows(score_list)

get_measures(os.path.join(ROOTDIR, "mixed/"), os.path.join(ROOTDIR, "out_stats_mixed.csv"))
get_measures(os.path.join(ROOTDIR, "denoised_const/"), os.path.join(ROOTDIR, "out_stats_dnconst3.csv"))
get_measures(os.path.join(ROOTDIR, "denoised_ols/"), os.path.join(ROOTDIR, "out_stats_dnols1.csv"))
get_measures(os.path.join(ROOTDIR, "denoised_qr/"), os.path.join(ROOTDIR, "out_stats_dnqr1.csv"))
