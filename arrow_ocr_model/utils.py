import cv2
import numpy as np


def preprocess_image(img_path, target_size=(64, 64)):
    img = cv2.imread(img_path)
    img = cv2.resize(img, target_size)
    img = img / 255.0  # Normalize
    img = np.expand_dims(img, axis=0)
    return img
