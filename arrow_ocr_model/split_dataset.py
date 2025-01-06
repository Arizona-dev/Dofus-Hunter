import os
import shutil
import random

# Paths
base_dir = "augmented"
train_dir = "data/train"
test_dir = "data/test"
directions = ["East", "West", "North", "South"]

# Create train/test directories
for split_dir in [train_dir, test_dir]:
    os.makedirs(split_dir, exist_ok=True)
    for direction in directions:
        os.makedirs(os.path.join(split_dir, direction), exist_ok=True)

# Split data
split_ratio = 0.8  # 80% train, 20% test
for direction in directions:
    files = os.listdir(os.path.join(base_dir, direction))
    random.shuffle(files)

    split_point = int(len(files) * split_ratio)
    train_files = files[:split_point]
    test_files = files[split_point:]

    # Move files
    for file in train_files:
        shutil.copy(
            os.path.join(base_dir, direction, file),
            os.path.join(train_dir, direction, file),
        )
    for file in test_files:
        shutil.copy(
            os.path.join(base_dir, direction, file),
            os.path.join(test_dir, direction, file),
        )
    print(f"Processed {direction}: {len(train_files)} train, {len(test_files)} test")
