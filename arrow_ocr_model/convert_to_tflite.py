import tensorflow as tf

# Paths
MODEL_PATH = "arrow_direction_cnn.h5"
TFLITE_PATH = "arrow_direction_cnn.tflite"

# Load model
model = tf.keras.models.load_model(MODEL_PATH)

# Convert to TFLite
converter = tf.lite.TFLiteConverter.from_keras_model(model)
tflite_model = converter.convert()

# Save TFLite model
with open(TFLITE_PATH, "wb") as f:
    f.write(tflite_model)
print(f"Model converted and saved as '{TFLITE_PATH}'")
