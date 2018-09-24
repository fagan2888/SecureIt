from threading import Thread

import cv2

from obj_detection.tf_api.tf_object_detection_api import TFObjectDetectionAPI, \
    PRETRAINED_faster_rcnn_inception_v2_coco_2018_01_28, PRETRAINED_mask_rcnn_inception_v2_coco_2018_01_28, \
    PRETRAINED_faster_rcnn_inception_resnet_v2_atrous_coco_2018_01_28
from obj_detection.yolo_api.yolo_keras_object_detection_api import YOLOObjectDetectionAPI
from tf_session.tf_session_runner import SessionRunner
from tf_session.tf_session_utils import Inference

# cap = cv2.VideoCapture(-1)
cap = cv2.VideoCapture('/home/developer/PycharmProjects/SecureIt/data/obj_tracking/videos/inputs/video1.avi')

session_runner = SessionRunner()
while True:
    ret, image = cap.read()
    if ret:
        break

detection = YOLOObjectDetectionAPI('yolo_api', True)
detector_ip = detection.get_in_pipe()
detector_op = detection.get_out_pipe()
detection.use_session_runner(session_runner)
detection.use_threading()

session_runner.start()
detection.run()


while True:
    ret, image = cap.read()
    if not ret:
        continue
    detector_ip.push(Inference(image.copy()))
    detector_op.wait()
    ret, inference = detector_op.pull()
    if ret:
        i_dets = inference.get_result()
        # print(i_dets.get_masks()[0].shape)
        frame = i_dets.anotate()
        cv2.imshow("", i_dets.anotate())
        cv2.waitKey(1)
        # cv2.imwrite("/home/developer/Desktop/folder/" + (str(count).zfill(5)) + ".jpg", frame)



# Thread(target=detect_objects).start()
