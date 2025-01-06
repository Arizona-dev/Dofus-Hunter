import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.utils import img_to_array, load_img

# Load the trained model
model = load_model("arrow_direction_cnn.h5")

# Define class labels
class_labels = ["East", "South", "West", "North"]  # Update as per your class order


def predict_direction(image_path):
    # Load the image and preprocess
    img = load_img(image_path, target_size=(64, 64))  # Ensure the size matches training
    img_array = img_to_array(img)
    img_array = img_array / 255.0  # Normalize to [0, 1]
    img_array = np.expand_dims(img_array, axis=0)  # Add batch dimension

    # Predict the class
    predictions = model.predict(img_array)
    predicted_index = np.argmax(predictions, axis=1)[
        0
    ]  # Get the index of the highest probability
    predicted_label = class_labels[predicted_index]
    confidence = np.max(predictions)  # Get the confidence of the prediction

    return predicted_label, confidence


# Test with an example image
image_path = "real/South/South.png"  # Replace with your test image path
predicted_direction, confidence = predict_direction(image_path)

print(f"Predicted Direction: {predicted_direction}")
print(f"Confidence: {confidence * 100:.2f}%")
