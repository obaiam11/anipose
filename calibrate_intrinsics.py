#!/usr/bin/env python3

import cv2
from cv2 import aruco
from tqdm import tqdm, trange
import numpy as np
import sys
import itertools
import os, os.path
from glob import glob
from collections import defaultdict
import toml
from time import time
import re

def get_video_params(fname):
    cap = cv2.VideoCapture(fname)

    params = dict()
    params['width'] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    params['height'] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    params['fps'] = cap.get(cv2.CAP_PROP_FPS)

    cap.release()

    return params

def get_corners(fname, board):
    cap = cv2.VideoCapture(fname)

    length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    allCorners = []
    allIds = []

    for i in trange(length, ncols=70):
        ret, frame = cap.read()
        if not ret:
            break

        if i % 10 != 0:
            continue

        gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        grayb = gray

        params = aruco.DetectorParameters_create()
        params.cornerRefinementMethod = aruco.CORNER_REFINE_CONTOUR
        params.adaptiveThreshWinSizeMin = 100
        params.adaptiveThreshWinSizeMax = 700
        params.adaptiveThreshWinSizeStep = 50
        params.adaptiveThreshConstant = 5

        corners, ids, rejectedImgPoints = aruco.detectMarkers(grayb, board.dictionary, parameters=params)

        detectedCorners, detectedIds, rejectedCorners, recoveredIdxs = aruco.refineDetectedMarkers(grayb, board, corners, ids, rejectedImgPoints, parameters=params)

        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        if len(detectedCorners) >= 2:
            allCorners.append(detectedCorners)
            allIds.append(detectedIds)


    cap.release()

    return allCorners, allIds

def trim_corners(allCorners, allIds, maxBoards=85):
    counts = np.array([len(cs) for cs in allCorners])
    sort = -counts + np.random.random(size=counts.shape)/2
    subs = np.argsort(sort)[:maxBoards]
    allCorners = [allCorners[ix] for ix in subs]
    allIds = [allIds[ix] for ix in subs]
    return allCorners, allIds


def reformat_corners(allCorners, allIds, numsq=2):
    markerCounter = np.array([len(cs) for cs in allCorners])
    allCornersConcat = itertools.chain.from_iterable(allCorners)
    allIdsConcat = itertools.chain.from_iterable(allIds)

    allCornersConcat = np.array(list(allCornersConcat))
    allIdsConcat = np.array(list(allIdsConcat))

    return allCornersConcat, allIdsConcat, markerCounter

def calibrate_aruco(allCornersConcat, allIdsConcat, markerCounter, board, video_params):

    print("calibrating...")
    tstart = time()

    cameraMat = np.eye(3)
    distCoeffs = np.zeros(5)
    dim = (video_params['width'], video_params['height'])
    error, cameraMat, distCoeffs, rvecs, tvecs = aruco.calibrateCameraAruco(allCornersConcat, allIdsConcat, markerCounter, board, dim, cameraMat, distCoeffs)

    tend = time()
    tdiff = tend - tstart
    print("calibration took {} minutes and {:.1f} seconds".format(
        int(tdiff/60), tdiff-int(tdiff/60)*60))

    out = dict()
    out['error'] = error
    out['camera_mat'] = cameraMat.tolist()
    out['dist_coeff'] = distCoeffs.tolist()
    out['width'] = video_params['width']
    out['height'] = video_params['height']
    out['fps'] = video_params['fps']

    return out

def calibrate_camera(fnames, numsq=2):
    allCorners = []
    allIds = []
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    board = aruco.GridBoard_create(numsq, numsq, 4, 1, dictionary)

    video_params = get_video_params(fnames[0])

    for fname in fnames:
        someCorners, someIds = get_corners(fname, board)
        allCorners.extend(someCorners)
        allIds.extend(someIds)

    allCorners, allIds = trim_corners(allCorners, allIds, maxBoards=85)
    allCornersConcat, allIdsConcat, markerCounter = reformat_corners(allCorners, allIds, numsq)

    print()

    print("found {} markers, {} boards, {} complete boards".format(
        len(allCornersConcat), len(markerCounter),
        np.sum(markerCounter == numsq*numsq)))

    calib_params = calibrate_aruco(allCornersConcat, allIdsConcat, markerCounter, board, video_params)

    return calib_params


def get_folders(path):
    folders = next(os.walk(path))[1]
    return sorted(folders)

def get_cam_name(config, fname):
    basename = os.path.basename(fname)
    basename = os.path.splitext(basename)[0]

    cam_regex = config['cam_regex']
    match = re.search(cam_regex, basename)
    if not match:
        return None
    else:
        return match.groups()[0]

def process_session(config, session_path):
    pipeline_videos_raw = config['pipeline_videos_raw']
    pipeline_calibration = config['pipeline_calibration']

    videos = glob(os.path.join(session_path,
                               pipeline_videos_raw,
                               config['calibration_prefix'] + '*.avi'))
    videos = sorted(videos)

    cam_names = [get_cam_name(config, vid) for vid in videos]
    cam_names = sorted(set(cam_names))

    cam_videos = defaultdict(list)

    for vid in videos:
        cname = get_cam_name(config, vid)
        cam_videos[cname].append(vid)

    for cname in cam_names:
        fnames = cam_videos[cname]
        outname_base = 'intrinsics_{}.toml'.format(cname)
        outdir = os.path.join(session_path, pipeline_calibration)
        os.makedirs(outdir, exist_ok=True)
        outname = os.path.join(outdir, outname_base)
        print(outname)
        if os.path.exists(outname):
            continue
        else:
            calib = calibrate_camera(fnames)
            with open(outname, 'w') as f:
                toml.dump(calib, f)



def calibrate_intrinsics_all(config):
    pipeline_prefix = config['path']

    sessions = get_folders(pipeline_prefix)

    for session in sessions:
        print(session)

        session_path = os.path.join(pipeline_prefix, session)
        process_session(config, session_path)