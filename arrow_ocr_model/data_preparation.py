import os
import cv2
import numpy as np

# Set paths
DATASET_DIR = "dataset"
OUTPUT_DIR = "processed_dataset"
TARGET_SIZE = (64, 64)

def preprocess_images(input_dir, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    for subdir in os.listdir(input_dir):
        subpath = os.path.join(input_dir, subdir)
        if os.path.isdir(subpath):
            output_subdir = os.path.join(output_dir, subdir)
            os.makedirs(output_subdir, exist_ok=True)

            for img_name in os.listdir(subpath):
                img_path = os.path.join(subpath, img_name)
                img = cv2.imread(img_path)
                if img is not None:
                    img_resized = cv2.resize(img, TARGET_SIZE)
                    cv2.imwrite(os.path.join(output_subdir, img_name), img_resized)

if __name__ == "__main__":
    preprocess_images(DATASET_DIR, OUTPUT_DIR)
    print(f"Images processed and saved in {OUTPUT_DIR}")
