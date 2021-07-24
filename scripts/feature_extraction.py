from prepare_dataset import check_exists, check_file_extension, rename_extension, supplement_label
from analyze_metadata import get_df_counts
from clean_classes import check_sample_size

import pandas as pd
import numpy as np
from numpy import dot
from numpy.linalg import norm
from itertools import combinations
import os
import glob

from PIL import Image

import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras import Sequential, initializers
from tensorflow.keras.layers import Conv2D, BatchNormalization, MaxPool2D, Flatten, Dense, Dropout, Input
from tensorflow.keras.applications import EfficientNetB0


# Set CPU only
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Limit number of GPU used to 1
# tf.config.set_soft_device_placement(True)
# tf.debugging.set_log_device_placement(True)


# Global Variables
model_dir = "/home/stan/cytoimagenet/model/"
annotations_dir = "/home/stan/cytoimagenet/annotations/"


def build_alexnet():
    """Build AlexNet with randomly initialized weights"""
    # Random Initializers
    weights_init = initializers.RandomNormal(mean=0.0, stddev=0.05, seed=None)
    bias_init = 'zeros'

    # Build Model
    model = Sequential(name="AlexNet")
    model.add(Input(shape=(224, 224, 3)))

    # Conv Block
    model.add(Conv2D(filters=96, kernel_size=(11,11), strides=(4,4), activation='relu',
                     kernel_initializer=weights_init,
                     bias_initializer=bias_init
                     ))
    model.add(BatchNormalization())

    # Conv Block
    model.add(MaxPool2D(pool_size=(3,3), strides=(2,2)))
    model.add(Conv2D(filters=256, kernel_size=(5,5), strides=(1,1), activation='relu', padding="same",
                     kernel_initializer=weights_init,
                     bias_initializer=bias_init
                     ))
    model.add(BatchNormalization())

    # Conv Block
    model.add(MaxPool2D(pool_size=(3,3), strides=(2,2)))
    model.add(Conv2D(filters=384, kernel_size=(3,3), strides=(1,1), activation='relu', padding="same",
                     kernel_initializer=weights_init,
                     bias_initializer=bias_init
                     ))
    model.add(BatchNormalization())

    # Conv Block
    model.add(Conv2D(filters=384, kernel_size=(3,3), strides=(1,1), activation='relu', padding="same",
                     kernel_initializer=weights_init,
                     bias_initializer=bias_init
                     ))
    model.add(BatchNormalization())
    model.add(Conv2D(filters=256, kernel_size=(3,3), strides=(1,1), activation='relu', padding="same",
                     kernel_initializer=weights_init,
                     bias_initializer=bias_init
                     ))
    model.add(BatchNormalization())

    model.add(MaxPool2D(pool_size=(3,3), strides=(2,2)))
    model.add(Flatten())

    # Fully Connected Block
    model.add(Dense(4096, activation='relu',
                    kernel_initializer=weights_init,
                    bias_initializer=bias_init
                    ))
    model.add(Dropout(0.5))
    model.add(Dense(4096, activation='relu',
                    kernel_initializer=weights_init,
                    bias_initializer=bias_init
                    ))
    # model.add(Dropout(0.5))
    # model.add(Dense(10, activation='softmax',
    #                 kernel_initializer=weights_init,
    #                 bias_initializer=bias_init
    #                 ))
    return model


def test_datagen(label: str, label_dir):
    """Return dataframe compatible with ImageDataGenerator.flow_from_dataframe
    from tensorflow keras.

    Since API is only compatible with jpg, png and gif files. Check that all files

    """
    df = pd.read_csv(f"{annotations_dir}classes/{label_dir}/{label}.csv")
    df.apply(check_exists, axis=1)
    # df.apply(check_file_extension, axis=1)
    # df["filename"] = df.filename.map(rename_extension)
    df['full_name'] = df.apply(lambda x: f"{x.path}/{x.filename}", axis=1)
    return df


def get_activations_for(model, label: str, directory: str = "imagenet-activations/base", label_dir: str = ""):
    """Load <model>. Extract activations for images under label.
    """
    # Create Image Generator for <label>
    test_gen = ImageDataGenerator(rescale=1./255).flow_from_dataframe(
        dataframe=test_datagen(label, label_dir),
        directory=None,
        x_col='full_name',
        color_mode='rgb',
        batch_size=1,
        target_size=(224, 224),
        shuffle=False,
        class_mode=None,
        interpolation='bilinear',
        seed=1,
        validate_filenames=False
    )

    # Save image embeddings
    activations = model.predict(test_gen)
    if not os.path.exists(f"{model_dir}{directory}"):
        os.mkdir(f"{model_dir}{directory}")

    pd.DataFrame(activations).to_csv(f"{model_dir}{directory}/{label}_activations.csv", index=False)
    return activations


def intra_cos_sims(label_features: np.array, n=3000) -> list:
    """Calculate intra cosine similarities between images images (features) from one
    label. Estimate by calculating cosine similarity for at most <n> pairs.

    Return list of pairwise cosine similarities.

    ==Parameters==:
        label_features: np.array where each row is a feature vector for one
                        image
    """
    pairs = np.array(list(combinations(label_features, 2)))
    if len(pairs) > n:
        pairs = pairs[np.random.choice(len(pairs), n, replace=False)]

    cos_sims = []
    for pair in pairs:
        cos_sims.append(cosine_similarity(pair))
    return cos_sims


def inter_cos_sims(label_features: np.array, other_features: np.array,
                   n=3000) -> list:
    """Calculate inter cosine similarities between images (features) from a
    label and images from any label. Estimate by calculating cosine similarity
    for <n> pairs.

    Return list of pairwise cosine similarities.

    ==Parameters==:
        label_features: np.array where each row is a feature vector for one
                        image
        other_features: np.array where each row is a feature vector for one
                        image
    """
    cos_sims = []
    for i in range(n):
        cos_sims.append(cosine_similarity((label_features[np.random.choice(len(label_features), 1, replace=True)].flatten(),
                                           other_features[np.random.choice(len(other_features), 1, replace=False)].flatten())))
    return cos_sims


def cosine_similarity(img1_img2: tuple) -> float:
    """Return cosine similarity between image features of <img1_img2>[0] and
    <img1_img2>[1].
    """
    img1, img2 = img1_img2
    return dot(img1, img2) / (norm(img1) * norm(img2))


def calculate_cos_sim(labels: list, prefix: str, activation_loc: str):
    """Calculate and save all pairwise cosine similarities between images per
    label in <labels> in separate files. Save mean and standard deviation in
    <model_dir>similarity/<prefix>-label_similarities.csv

    ==Parameters==:
        labels: list of labels to calculate intra - cosine similarity
        prefix: prefix to attach when saving similarity metrics
            - either 'random' or 'imagenet'
        activation_loc: subdirectory in <model_dir> to find/save activations
    """
    global model_dir
    # Similarity Accumulators
    sim_label = labels.copy()
    sim_mean = []
    sim_std = []

    for label in labels:
        try:
            # Extract image embeddings
            if os.path.exists(f"{model_dir}{activation_loc}{label}_activations.csv"):
                features = pd.read_csv(f"{model_dir}{activation_loc}{label}_activations.csv").to_numpy()
            else:
                features = get_activations_for(model, label, directory=activation_loc)

            # Get all pairwise cosine similarities
            if os.path.exists(f"{model_dir}similarity/{label}_{prefix}-sim.npy"):
                cos_sims = np.load(f"{model_dir}similarity/{label}_{prefix}_sim.npy")
            else:
                print(f"Calculating Cosine Similarity for {label}...")
                cos_sims = np.array(intra_cos_sims(features))
                np.save(f"{model_dir}similarity/{label}_{prefix}_sim.npy", cos_sims)

            print(f"{label} Similarity | mean: {cos_sims.mean()}, sd: {cos_sims.std()}")
            print()

            sim_mean.append(cos_sims.flatten().mean())
            sim_std.append(cos_sims.flatten().std())
        except:
            print(label + " failed!")
            sim_label.remove(label)

    if os.path.exists(f"{model_dir}similarity/{prefix}-label_similarities.csv"):
        df_sim = pd.concat([pd.read_csv(f"{model_dir}similarity/{prefix}-label_similarities.csv"),
                            pd.DataFrame({"label": sim_label,
                                          "mean_sim": sim_mean,
                                          "std_sim": sim_std})]
                           )
    else:
        df_sim = pd.DataFrame({"label": sim_label,
                               "mean_sim": sim_mean,
                               "std_sim": sim_std})
    df_sim.to_csv(f"{model_dir}similarity/{prefix}-label_similarities.csv", index=False)


def get_summary_similarities(embeds: pd.DataFrame, labels: np.array):
    """Return dataframe of mean inter cosine similarity and mean intra
    cosine similarity for each label.
    """
    df = pd.DataFrame(columns=["label", "intra_cos", "inter_cos"])
    for label in np.unique(labels):
        # TODO: Intra-Cosine Similarity
        intra_sims = np.array(intra_cos_sims(embeds[labels == label]))
        # TODO: Inter-Cosine Similarity
        inter_sims = np.array(inter_cos_sims(embeds[labels == label],
                                             embeds[labels != label]))

        curr_sims = pd.DataFrame({"label": label, "intra_cos": intra_sims.mean(),
                                  "inter_cos": inter_sims.mean()}, index=[0])
        df = pd.concat([df, curr_sims], ignore_index=True)
    return df


if __name__ == "__main__" and "D:\\" not in os.getcwd():
    # Choose model
    model_choice = "efficient"

    # Build model.
    if model_choice == "alex":  # Randomly Initialized AlexNet
        model = build_alexnet()
        # model.save_weights(f"{model_dir}random_alex.h5")
        model.load_weights(f"{model_dir}random_alex.h5")

        # Directory to save activations
        activation_loc = "random_model-activations/"
        prefix = 'random'
    else:   # Pre-trained EfficientNetB0
        model = EfficientNetB0(weights="imagenet",
                               include_top=False,
                               input_shape=(224, 224, 3),
                               pooling="max")
        model.trainable = False

        # Directory to save activations
        activation_loc = "imagenet-activations/"
        prefix = 'imagenet'

    # labels = []
    # for file in glob.glob(f"{annotations_dir}classes/*.csv"):
    #     labels.append(file.split("classes/")[-1].replace(".csv", ""))

    chosen = ['human', 'nucleus', 'cell membrane',
              'white blood cell', 'kinase',
              'wildtype', 'difficult',
              'nematode', 'yeast', 'bacteria',
              ]

    for label in chosen[::]:
        # if not os.path.isfile(f"{model_dir}{activation_loc}{label}_activations.csv"):
        #     check_sample_size(label)
        features = get_activations_for(model, label, directory=activation_loc, label_dir="")

        # TODO: Upsampled
        supplement_label(label)
        features = get_activations_for(model, label, directory=activation_loc+"upsampled/", label_dir="upsampled")
        print(f"Finished Feature Extraction for {label}!")



