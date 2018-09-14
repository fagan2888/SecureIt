import time
from threading import Thread

import cv2

from obj_detection.tf_api.tf_object_detection_api import TFObjectDetectionAPI, \
    PRETRAINED_faster_rcnn_inception_v2_coco_2018_01_28, PRETRAINED_mask_rcnn_inception_v2_coco_2018_01_28
from obj_tracking.sort.sort import Sort
from tf_session.tf_session_runner import SessionRunner

tracker = Sort(max_age_secs=120, min_hits=10)  # create instance of the SORT tracker

session_runner = SessionRunner()
session_runner.start()

cap0 = cv2.VideoCapture(0)
while True:
    ret, image0 = cap0.read()
    if ret:
        break

detection0 = TFObjectDetectionAPI(PRETRAINED_mask_rcnn_inception_v2_coco_2018_01_28, image0.shape,
                                  'tf_api_0', True)
detection0.use_session_runner(session_runner)
ip0 = detection0.get_in_pipe()
op0 = detection0.get_out_pipe()
detection0.run()

cap1 = cv2.VideoCapture(1)
while True:
    ret, image1 = cap1.read()
    if ret:
        break

detection1 = TFObjectDetectionAPI(PRETRAINED_faster_rcnn_inception_v2_coco_2018_01_28, image1.shape,
                                  'tf_api_1', True)
detection1.use_session_runner(session_runner)
ip1 = detection1.get_in_pipe()
op1 = detection1.get_out_pipe()
detection1.run()


def readvideo():
    while True:
        re, img0 = cap0.read()
        if re:
            ip0.push(img0.copy())
        re, img1 = cap1.read()
        if re:
            ip1.push(img1.copy())
        time.sleep(0.025)


Thread(target=readvideo).start()
flag = True
while True:
    # flag = not flag
    if flag:
        op = op1
        name = "cam1"
    else:
        op = op0
        name = "cam0"

    ret, inference = op.pull()
    if ret:
        detections = inference.get_boxes(normalized=False)
        frame = inference.get_image()
        classes = inference.get_classes()
        person_detections = []
        scores = inference.get_scores()
        for i in range(len(classes)):
            if classes[i] == inference.get_category('person') and scores[i] > .75:
                person_detections.append([detections[i][1], detections[i][0], detections[i][3], detections[i][2]])
        start_time = time.time()
        trackers = tracker.update(frame, person_detections)
        cycle_time = time.time() - start_time

        for d in trackers:
            cv2.rectangle(frame, (int(d[0]), int(d[1])), (int(d[2]), int(d[3])), (255, 0, 0), 2)
            cv2.putText(frame, str(d[4]), (int(d[0]), int(d[1])), cv2.FONT_HERSHEY_COMPLEX, 0.75, (0, 0, 255))

        cv2.imshow(name, frame)
        cv2.waitKey(1)
    else:
        op.wait()

# t = Thread(target=process, args=(op0,"cam0", tracker))
# t.start()
# t.join()


# Thread(target=process, args=(op1,"cam1",)).start()