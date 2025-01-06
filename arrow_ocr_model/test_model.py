from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing.image import ImageDataGenerator

# Paths
TEST_DIR = "data/test"
MODEL_PATH = "arrow_direction_cnn.h5"

# Load model
model = load_model(MODEL_PATH)

# Data Generator
datagen = ImageDataGenerator(rescale=1.0 / 255.0)

test_data = datagen.flow_from_directory(
    TEST_DIR, target_size=(64, 64), batch_size=32, class_mode="categorical"
)

# Evaluate model
test_loss, test_accuracy = model.evaluate(test_data)
print(f"Test Accuracy: {test_accuracy * 100:.2f}%")
