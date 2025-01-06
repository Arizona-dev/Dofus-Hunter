import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image

# Constants
IMG_SIZE = (64, 64)
MODEL_PATH = "arrow_direction_cnn.h5"
LABELS = ["East", "South", "West", "North"]

# Load model
model = load_model(MODEL_PATH)


def predict_arrow(img_path):
    img = image.load_img(img_path, target_size=IMG_SIZE)
    img_array = image.img_to_array(img) / 255.0
    img_array = np.expand_dims(img_array, axis=0)

    predictions = model.predict(img_array)
    predicted_class = LABELS[np.argmax(predictions)]
    confidence = np.max(predictions) * 100
    return predicted_class, confidence


if __name__ == "__main__":
    img_path = input("Enter the path to the arrow image: ")
    direction, confidence = predict_arrow(img_path)
    print(f"Predicted Direction: {direction} (Confidence: {confidence:.2f}%)")
