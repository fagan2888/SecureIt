
import colorsys
from os.path import dirname, realpath

import cv2
import os
from threading import Thread
from timeit import default_timer as timer

import numpy as np
from keras import backend as K
from keras.models import load_model
from keras.layers import Input
from PIL import Image, ImageFont, ImageDraw
import tensorflow as tf

from obj_detection.obj_detection_utils import InferedDetections
from obj_detection.yolo_api.yolo_keras.model import yolo_eval, yolo_body, tiny_yolo_body
from obj_detection.yolo_api.yolo_keras.utils import letterbox_image
import os
from keras.utils import multi_gpu_model

from tf_session.tf_session_runner import SessionRunnable
from tf_session.tf_session_utils import Pipe

from data.obj_detection.yolo_api.yolo_keras.pretrained import path as pretrained_path
from data.obj_detection.yolo_api.yolo_keras.data import path as data_path

class YOLOObjectDetectionAPI():
    _defaults = {
        "model_path": pretrained_path.get()+'/yolo_v3.h5',
        "anchors_path": data_path.get()+'/yolo_anchors.txt',
        "classes_path": data_path.get()+'/coco.names',
        "score": 0.3,
        "iou": 0.45,
        "model_image_size": (416, 416),
        "gpu_num": 1,
    }
    @staticmethod
    def __get_dir_path():
        return dirname(realpath(__file__))

    @classmethod
    def get_defaults(cls, n):
        if n in cls._defaults:
            return cls._defaults[n]
        else:
            return "Unrecognized attribute name '" + n + "'"

    def __init__(self, graph_prefix=None, flush_pipe_on_read=False):
        self.__dict__.update(self._defaults)  # set up default values
        # self.__dict__.update(kwargs) # and update with user overrides
        YOLOObjectDetectionAPI.class_names, self.__category_dict = self._get_class()
        YOLOObjectDetectionAPI.anchors = self._get_anchors()
        self.__graph_prefix = graph_prefix
        self.__flush_pipe_on_read = flush_pipe_on_read
        self.__thread = None
        self.__in_pipe = Pipe(self.__in_pipe_process)
        self.__out_pipe = Pipe(self.__out_pipe_process)

        self.__run_session_on_thread = False

    def use_threading(self, run_on_thread=True):
        self.__run_session_on_thread = run_on_thread

    def use_session_runner(self, session_runner):
        self.__session_runner = session_runner
        K.set_session(session_runner.get_session())
        self.__tf_sess = K.get_session()
        self.boxes, self.scores, self.classes = self.generate()

    def __in_pipe_process(self, inference):

        image = inference.get_input()
        pil_image = Image.fromarray(image)

        if self.model_image_size != (None, None):
            assert self.model_image_size[0] % 32 == 0, 'Multiples of 32 required'
            assert self.model_image_size[1] % 32 == 0, 'Multiples of 32 required'
            boxed_image = letterbox_image(pil_image, tuple(reversed(self.model_image_size)))
        else:
            new_image_size = (pil_image.width - (pil_image.width % 32),
                              pil_image.height - (pil_image.height % 32))
            boxed_image = letterbox_image(pil_image, new_image_size)
        data = np.array(boxed_image, dtype='float32')

        data /= 255.
        data = np.expand_dims(data, 0)  # Add batch dimension.

        inference.set_data(data)
        inference.get_meta_dict()['PIL'] = pil_image
        if inference.get_return_pipe():
            inference.set_flush(self.__out_pipe)
        return inference
        # return image

    def __out_pipe_process(self, result):
        (out_boxes, out_classes, out_scores), inference = result
        out_boxes = np.array([[0 if y < 0 else y for y in x] for x in out_boxes])
        result = InferedDetections(inference.get_input(), len(out_boxes), out_boxes, out_classes, out_scores, masks=None,
                                   is_normalized=False, get_category_fnc=self.get_category, annotator=self.annotate)
        inference.set_result(result)
        return inference

    def get_in_pipe(self):
        return self.__in_pipe

    def get_out_pipe(self):
        return self.__out_pipe

    def _get_class(self):
        dir_path = YOLOObjectDetectionAPI.__get_dir_path()
        classes_path = os.path.expanduser(self.classes_path)
        with open(classes_path) as f:
            class_names = f.readlines()
        class_names = [c.strip() for c in class_names]
        category_dict = {}
        for id, name in enumerate(class_names):
            category_dict[id] = name
            category_dict[name] = id
        return class_names, category_dict

    def _get_anchors(self):
        dir_path = YOLOObjectDetectionAPI.__get_dir_path()
        anchors_path = os.path.expanduser(self.anchors_path)
        with open(anchors_path) as f:
            anchors = f.readline()
        anchors = [float(x) for x in anchors.split(',')]
        return np.array(anchors).reshape(-1, 2)

    def generate(self):
        dir_path = YOLOObjectDetectionAPI.__get_dir_path()
        model_path = os.path.expanduser(self.model_path)
        assert model_path.endswith('.h5'), 'Keras model or weights must be a .h5 file.'

        # Load model, or construct model and load weights.
        num_anchors = len(self.anchors)
        num_classes = len(self.class_names)
        is_tiny_version = num_anchors == 6  # default setting
        try:
            self.yolo_model = load_model(model_path, compile=False)
        except:
            self.yolo_model = tiny_yolo_body(Input(shape=(None, None, 3)), num_anchors // 2, num_classes) \
                if is_tiny_version else yolo_body(Input(shape=(None, None, 3)), num_anchors // 3, num_classes)
            self.yolo_model.load_weights(self.model_path)  # make sure model, anchors and classes match
        else:
            assert self.yolo_model.layers[-1].output_shape[-1] == \
                   num_anchors / len(self.yolo_model.output) * (num_classes + 5), \
                'Mismatch between model and given anchor and class sizes'

        # print('{} model, anchors, and classes loaded.'.format(model_path))

        # Generate colors for drawing bounding boxes.
        hsv_tuples = [(x / len(self.class_names), 1., 1.)
                      for x in range(len(self.class_names))]
        YOLOObjectDetectionAPI.colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
        YOLOObjectDetectionAPI.colors = list(
            map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)),
                YOLOObjectDetectionAPI.colors))
        np.random.seed(10101)  # Fixed seed for consistent colors across runs.
        np.random.shuffle(YOLOObjectDetectionAPI.colors)  # Shuffle colors to decorrelate adjacent classes.
        np.random.shuffle(YOLOObjectDetectionAPI.colors)  # Shuffle colors to decorrelate adjacent classes.
        np.random.seed(None)  # Reset seed to default.


        # Generate output tensor targets for filtered bounding boxes.
        self.input_image_shape = K.placeholder(shape=(2,))
        if self.gpu_num >= 2:
            self.yolo_model = multi_gpu_model(self.yolo_model, gpus=self.gpu_num)

        boxes, scores, classes = yolo_eval(self.yolo_model.output, self.anchors,
                                           len(self.class_names), self.input_image_shape,
                                           score_threshold=self.score, iou_threshold=self.iou)
        return boxes, scores, classes

    def freeze_session(self, session, keep_var_names=None, output_names=None, clear_devices=True):
        """
        Freezes the state of a session into a pruned computation graph.

        Creates a new computation graph where variable nodes are replaced by
        constants taking their current value in the session. The new graph will be
        pruned so subgraphs that are not necessary to compute the requested
        outputs are removed.
        @param session The TensorFlowsion(detected_boxes, confidence_threshold=FLAGS.conf_threshold,
                                         iou_threshold=FLAGS.iou_threshold)

    draw_boxes(filtered_boxes, img, classes, (FLAGS.size, FLAGS.size))

    img.save(FLAGS.output_img) session to be frozen.
        @param keep_var_names A list of variable names that should not be frozen,
                              or None to freeze all the variables in the graph.
        @param output_names Names of the relevant graph outputs.
        @param clear_devices Remove the device directives from the graph for better portability.
        @return The frozen graph definition.
        """
        from tensorflow.python.framework.graph_util import convert_variables_to_constants
        graph = session.graph
        with graph.as_default():
            freeze_var_names = list(set(v.op.name for v in tf.global_variables()).difference(keep_var_names or []))
            output_names = output_names or []
            output_names += [v.op.name for v in tf.global_variables()]
            input_graph_def = graph.as_graph_def()
            if clear_devices:
                for node in input_graph_def.node:
                    node.device = ""
            frozen_graph = convert_variables_to_constants(session, input_graph_def,
                                                          output_names, freeze_var_names)
            return frozen_graph

    def run(self):
        if self.__thread is None:
            self.__thread = Thread(target=self.__run)
            self.__thread.start()

    def __run(self):
        while self.__thread:
            if self.__in_pipe.is_closed():
                self.__out_pipe.close()
                return

            ret, inference = self.__in_pipe.pull(self.__flush_pipe_on_read)
            if ret:
                self.__session_runner.get_in_pipe().push(
                    SessionRunnable(self.__job, inference, run_on_thread=self.__run_session_on_thread))
            else:
                self.__in_pipe.wait()

    def __job(self, inference):
        data = inference.get_data()
        pil_image = inference.get_meta_dict()['PIL']
        # image = inference.get_input()
        out_boxes, out_scores, out_classes = self.__tf_sess.run(
            [self.boxes, self.scores, self.classes],
            feed_dict={
                self.yolo_model.input: data,
                self.input_image_shape: [pil_image.size[1], pil_image.size[0]],
            })

        self.__out_pipe.push(((out_boxes, out_classes, out_scores), inference))

    def close_session(self):
        self.__tf_sess.close()

    @staticmethod
    def annotate(inference):
        annotated = inference.image.copy()
        image = Image.fromarray(inference.get_image())
        font = ImageFont.truetype(font='arial.ttf',
                                  size=np.floor(3e-2 * image.size[1] + 0.5).astype('int32'))
        thickness = 1#(image.size[0] + image.size[1]) // 300
        for i, c in reversed(list(enumerate(inference.get_classes()))):
            predicted_class = YOLOObjectDetectionAPI.class_names[c]
            box = inference.get_boxes_tlbr(normalized=False)[i]
            score = inference.get_scores()[i]

            label = '{} {:.2f}'.format(predicted_class, score)
            draw = ImageDraw.Draw(image)
            label_size = draw.textsize(label, font)

            top, left, bottom, right = box
            top = max(0, np.floor(top + 0.5).astype('int32'))
            left = max(0, np.floor(left + 0.5).astype('int32'))
            bottom = min(image.size[1], np.floor(bottom + 0.5).astype('int32'))
            right = min(image.size[0], np.floor(right + 0.5).astype('int32'))
            # print(label, (left, top), (right, bottom))

            if top - label_size[1] >= 0:
                text_origin = np.array([left, top - label_size[1]])
            else:
                text_origin = np.array([left, top + 1])

            # My kingdom for a good redistributable image drawing library.
            for i in range(thickness):
                draw.rectangle(
                    [left + i, top + i, right - i, bottom - i],
                    outline=YOLOObjectDetectionAPI.colors[c])
            draw.rectangle(
                [tuple(text_origin), tuple(text_origin + label_size)],
                fill=YOLOObjectDetectionAPI.colors[c])
            draw.text(text_origin, label, fill=(0, 0, 0), font=font)
            del draw
        return np.array(image)

    def get_category(self, category):
        return self.__category_dict[category]



