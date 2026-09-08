# DATA 589 — Applied Computer Vision and Deep Learning
# Quiz 1 — Practice Questions
### UBCO Master of Data Science

---

> **Purpose:** These practice questions help you prepare for Quiz 1. They cover the **style, format, and difficulty level** you can expect. The actual quiz may cover any topic from Lectures 1–4 and Labs 1–2.
>
> **Topics to study:**
> - Image representation (pixels, channels, resolution, color spaces)
> - Image formats (raster, vector, specialist), video containers vs. codecs
> - Core CV tasks (classification, detection, semantic & instance segmentation)
> - Datasets, benchmarks, and synthetic data concepts
> - Deep learning as representation learning; hand-crafted vs. learned features
> - Key milestones (Hubel & Wiesel, AlexNet/ImageNet 2012)
> - FCN limitations for image data
> - Convolution, filters, feature maps, weight sharing
> - Stride, padding, pooling, ReLU, softmax
> - Feature map dimension computation
> - CNN architecture: backbone vs. head
> - Object detection: R-CNN, Faster R-CNN, YOLO (two-stage vs. single-stage)
> - IoU, precision, recall, mAP
> - YOLO dataset format and training pipeline concepts
> - Limitations of CNNs (locality, long-range dependencies)
> - Attention, self-attention, query/key/value
> - Positional encoding, multi-head attention
> - Tokens and the Vision Transformer (ViT) intuition
> - PyTorch tensor conventions (B, C, H, W) and practical lab concepts
>
> **Tip:** Focus on *understanding concepts*, not memorizing code syntax or PyTorch function signatures.

---

## Part A — Multiple Choice

*Select the single best answer for each question.*

---

### Lecture 1 Topics: CV Foundations, Images, Video, Tasks, Synthetic Data

---

**Q1.** A digital color image has shape (1080, 1920, 3). Which of the following is true?

A. The image has 1080 color channels  
B. The image is 1920 pixels tall and 1080 pixels wide  
C. The image is 1080 pixels tall, 1920 pixels wide, with 3 color channels (e.g., RGB)  
D. The "3" refers to three separate images stacked together  

---

**Q2.** OpenCV loads a color image in **BGR** format by default. A student displays the image directly using `matplotlib` (which expects RGB) without converting. What will happen?

A. The image will appear identical to the original  
B. The red and blue channels will be swapped, distorting the colors  
C. The image will be displayed as grayscale  
D. Python will raise an error  

---

**Q3.** Which image format supports an **alpha (transparency) channel**?

A. JPEG  
B. PNG  
C. RAW  
D. SVG  

---

**Q4.** A video file is described as an MP4 container using the H.265 codec. Which interpretation is correct?

A. MP4 is the compression algorithm and H.265 is the file wrapper  
B. MP4 holds the video/audio/metadata together; H.265 is the algorithm that compresses the video stream  
C. MP4 and H.265 refer to the same thing — the video's resolution  
D. H.265 determines the frame rate; MP4 determines the resolution  

---

**Q5.** Which of the following is an **object-level** computer vision task?

A. Depth estimation  
B. Action recognition  
C. Object detection  
D. Image classification  

---

**Q6.** What is the difference between **semantic segmentation** and **instance segmentation**?

A. Semantic segmentation uses bounding boxes; instance segmentation uses pixel masks  
B. Semantic segmentation assigns a class to every pixel but does not separate individual objects of the same class; instance segmentation assigns a unique mask to each object instance  
C. Instance segmentation only works on videos; semantic segmentation works on images  
D. They are identical tasks with different names  

---

**Q7.** Which of the following is **NOT** an advantage of synthetic data mentioned in the lectures?

A. Scale — millions of perfectly labeled frames can be generated  
B. Coverage of rare events and edge cases  
C. Guaranteed perfect performance on real-world test sets  
D. Control over class balance and targeted scenarios  

---

**Q8.** The lectures describe two categories of synthetic data generation. Which pair is correct?

A. Supervised learning and unsupervised learning  
B. Physically based rendering (e.g., Blender, Unreal Engine) and generative methods (e.g., CycleGAN, diffusion models)  
C. Manual annotation and crowd-sourcing  
D. Transfer learning and fine-tuning  

---

### Lecture 2 Topics: Deep Learning, Representation Learning, FCN, Convolution Basics

---

**Q9.** Which concept introduced the idea that visual processing occurs **hierarchically** — from simple edges to complex patterns?

A. AlexNet  
B. Hubel & Wiesel's visual cortex experiments  
C. The ImageNet dataset  
D. The transformer architecture  

---

**Q10.** What is the best description of **representation learning** in the context of deep learning?

A. Manually designing features such as edge detectors and color histograms  
B. The model automatically discovers the feature representations needed for the task directly from raw data  
C. Using only principal component analysis to reduce dimensions  
D. Representation learning is only applicable to text, not images  

---

**Q11.** The 2012 ImageNet competition is described as the "Big Bang" of deep learning. Which three factors made AlexNet's success possible?

A. Small dataset, CPU training, shallow architecture  
B. Large-scale data (ImageNet), GPU compute, deep algorithmic innovations (ReLU, Dropout)  
C. Manual feature engineering, small filters, unsupervised learning  
D. Transfer learning, data augmentation, and attention mechanisms  

---

**Q12.** Why are **fully connected networks (FCNs)** considered a poor choice for image data?

A. They cannot use non-linear activation functions  
B. They require flattening the image to a 1-D vector, which destroys spatial structure, and they have far too many parameters for high-dimensional images  
C. They cannot be trained using gradient descent  
D. They can only process one-channel (grayscale) images  

---

**Q13.** Which statement about convolution filters in a CNN is **TRUE**?

A. Each filter looks at the entire image at once  
B. Each filter operates on a small local patch and the same weights are reused across all spatial locations (weight sharing)  
C. Filters in CNNs must be manually designed by the engineer  
D. Filters can only detect edges, not textures or shapes  

---

**Q14.** When a convolution filter slides across an image, the output is called:

A. An activation function  
B. A weight matrix  
C. A feature map  
D. A kernel output vector  

---

### Lecture 3 Topics: CNN Architecture, Pooling, Object Detection

---

**Q15.** What does **ReLU** (Rectified Linear Unit) do?

A. Normalizes pixel values to the range [0, 1]  
B. Replaces all negative values with zero and keeps positive values unchanged  
C. Doubles the spatial resolution of the feature map  
D. Computes the softmax probability distribution  

---

**Q16.** Why is a non-linear activation (like ReLU) needed after convolution layers?

A. To increase the number of feature maps  
B. Without non-linearity, stacking convolution layers results in a single linear operation, which cannot model complex patterns  
C. To reduce the number of parameters  
D. To convert the image from BGR to RGB  

---

**Q17.** Which of the following statements about **pooling** is FALSE?

A. Max pooling selects the maximum value from each local region  
B. Pooling reduces the spatial resolution of feature maps  
C. Pooling layers have learnable parameters updated during training  
D. Pooling provides some invariance to small spatial shifts  

---

**Q18.** If the input to a Conv2d layer is 32 × 32 with 3 channels and we apply **64 filters** of size 3 × 3 with stride 1 and padding 1, what is the output shape?

A. 30 × 30 × 64  
B. 32 × 32 × 64  
C. 32 × 32 × 3  
D. 16 × 16 × 64  

---

**Q19.** An input of size 28 × 28 is processed by a Conv2d layer with kernel 3 × 3, stride 1, and padding 0. What is the output spatial size?

A. 28 × 28  
B. 26 × 26  
C. 27 × 27  
D. 14 × 14  

---

**Q20.** In a CNN classification architecture, the **softmax function** is used because:

A. It detects edges more accurately  
B. It produces a probability distribution where all class scores sum to 1  
C. It replaces the need for convolution layers  
D. It increases the spatial resolution of the output  

---

**Q21.** In a CNN, the **backbone** and the **head** refer to:

A. The backbone is the classification layer; the head extracts features  
B. The backbone learns hierarchical visual features (edges, textures, shapes); the head maps those features to the task output (e.g., class scores)  
C. They are the same component with different names  
D. The backbone only works for detection; the head only works for classification  

---

**Q22.** What is the key difference between **R-CNN** and **Faster R-CNN**?

A. R-CNN uses a single-stage pipeline; Faster R-CNN uses two stages  
B. R-CNN uses manually defined region proposals; Faster R-CNN replaces them with a learnable Region Proposal Network (RPN) that shares features with the classifier  
C. Faster R-CNN cannot produce bounding boxes  
D. R-CNN is faster than Faster R-CNN  

---

**Q23.** YOLO is described as a **single-stage** object detector. What does this mean?

A. It uses one convolutional layer and nothing else  
B. It generates region proposals first, then classifies each one  
C. It predicts bounding boxes, confidence, and class probabilities in one forward pass without separate region proposals  
D. It can only detect one object per image  

---

**Q24.** Which of the following is a known **limitation of early YOLO versions**?

A. It cannot run on GPUs  
B. It struggles with small objects and has less precise localization than two-stage detectors  
C. It requires manual region proposals  
D. It cannot perform end-to-end training  

---

### Lecture 4 Topics: Attention, Self-Attention, Transformers, ViT

---

**Q25.** What is the **primary limitation of CNNs** that motivates attention mechanisms?

A. CNNs cannot learn any visual patterns  
B. CNNs process local patches only and have no direct mechanism to model long-range dependencies between distant regions  
C. CNNs require more data than transformers  
D. CNNs cannot be trained with backpropagation  

---

**Q26.** In the self-attention mechanism, what are the roles of **Query (Q)**, **Key (K)**, and **Value (V)**?

A. Q compresses the input, K stores the loss, V stores the gradients  
B. Q represents what a token is *looking for*, K represents what a token *offers* for matching, V is the *information* shared based on the computed attention weights  
C. Q, K, and V are three independent models  
D. Q is the image, K is the label, V is the prediction  

---

**Q27.** In self-attention, the **attention score** between two tokens is computed by:

A. Subtracting the Query from the Value  
B. Computing the pairwise similarity (e.g., dot product) between the Query and Key vectors  
C. Averaging all token embeddings  
D. Applying max pooling over the Value vectors  

---

**Q28.** Why do transformers need **positional encoding**?

A. Because transformers process tokens one by one in sequence  
B. Because self-attention processes all tokens simultaneously with no inherent notion of order, so position information must be explicitly added  
C. Because positional encoding reduces the number of model parameters  
D. Because positional encoding replaces the Value vectors  

---

**Q29.** In **multi-head self-attention**, what is the purpose of using multiple heads?

A. All heads learn the same attention pattern for robustness  
B. Different heads can learn different types of relationships — one may focus on local structure while another captures long-range interactions  
C. Multiple heads are used only to increase the number of parameters  
D. Each head processes a different image in the batch  

---

**Q30.** In the context of the Vision Transformer (ViT), what is a **token**?

A. A single pixel of the image  
B. A vector representation (embedding) of an image patch that serves as a unit of information for the transformer  
C. The final class prediction  
D. A type of convolution filter  

---

### Lab-Specific Topics

---

**Q31.** In PyTorch, a batch of 16 RGB images of size 32 × 32 has tensor shape:

A. (16, 32, 32, 3)  
B. (3, 32, 32, 16)  
C. (16, 3, 32, 32)  
D. (32, 32, 3, 16)  

---

**Q32.** **Intersection over Union (IoU)** is defined as:

A. The area of the predicted box divided by the area of the ground-truth box  
B. The intersection area divided by the union area of the predicted and ground-truth boxes  
C. The number of correct predictions divided by total predictions  
D. The perimeter overlap of two bounding boxes  

---

---

## Part B — True or False

*State whether the statement is True or False, and provide a one-sentence justification.*

---

**Q33.** A grayscale image is represented as a 2-D array with intensity values typically ranging from 0 (black) to 255 (white).

True / False  
Justification: ___________

---

**Q34.** JPEG is the best image format when you need transparency (alpha channel).

True / False  
Justification: ___________

---

**Q35.** A video at 30 FPS contains 30 individual image frames for every second of footage.

True / False  
Justification: ___________

---

**Q36.** In traditional image processing, edge-detection filters are manually designed; in CNNs, equivalent filters are learned automatically during training.

True / False  
Justification: ___________

---

**Q37.** Stacking multiple convolution layers **without** any non-linear activation is equivalent to a single linear transformation.

True / False  
Justification: ___________

---

**Q38.** If a convolution filter has size 3 × 3 and the input has 3 channels (RGB), the filter actually has dimensions 3 × 3 × 3.

True / False  
Justification: ___________

---

**Q39.** In a CNN, each convolution filter produces one feature map. Applying 64 filters produces 64 feature maps stacked as the depth of the output.

True / False  
Justification: ___________

---

**Q40.** Increasing the **stride** in a convolution layer results in a **larger** output feature map.

True / False  
Justification: ___________

---

**Q41.** The **receptive field** of a neuron in a CNN refers to the region of the input image that influences that neuron's output. Deeper layers have larger receptive fields.

True / False  
Justification: ___________

---

**Q42.** In YOLO, the image is divided into a grid, and each grid cell predicts bounding boxes, a confidence score, and class probabilities.

True / False  
Justification: ___________

---

**Q43.** Faster R-CNN and YOLO are both considered **single-stage** object detectors.

True / False  
Justification: ___________

---

**Q44.** In multi-head self-attention, all heads are forced to learn the same attention pattern.

True / False  
Justification: ___________

---

**Q45.** An IoU threshold of 0.5 is commonly used to determine whether a detection counts as a True Positive.

True / False  
Justification: ___________

---

---

## Part C — Short Answer / Explanation

*Write concise, precise answers. Aim for 3–6 sentences per question.*

---

**Q46. (Image Fundamentals)**  
Explain how a color image is represented numerically. What do "pixels," "channels," and "resolution" mean? How is this different from a grayscale image?

---

**Q47. (Video Concepts)**  
Explain the difference between a video **container** (e.g., MP4, MKV) and a **codec** (e.g., H.264, AV1). Why are both needed?

---

**Q48. (Representation Learning)**  
What does it mean that "deep learning is representation learning"? How does this differ from the traditional machine-learning approach of hand-crafted features? Why does representation learning require large datasets?

---

**Q49. (FCN vs. CNN)**  
Explain why a fully connected network is inefficient for image data and how CNNs solve this problem. Mention at least two specific advantages of CNNs over FCNs for image processing.

---

**Q50. (CNN Spatial Computation)**  
A CNN processes a 32 × 32 RGB input through these layers:

1. Conv2d: 3 → 32 filters, kernel 3 × 3, stride 1, padding 1  
2. ReLU  
3. MaxPool2d: kernel 2 × 2, stride 2  

What is the output size (H × W × D) after each layer, and why? Which layer changes the spatial resolution?

---

**Q51. (Object Detection Comparison)**  
Compare **two-stage detectors** (e.g., Faster R-CNN) with **single-stage detectors** (e.g., YOLO). Describe the pipeline of each and explain the main trade-off between speed and accuracy.

---

**Q52. (Precision, Recall, and mAP)**  
An object detector produces these results on a test set: **Precision = 0.85, Recall = 0.40**.

(a) What does this tell you about the detector's behavior?  
(b) Would this be acceptable for a surveillance system where missing an intruder is very dangerous? Explain.  
(c) What metric summarizes detection quality across all classes?

---

**Q53. (CNN Limitations → Attention)**  
Describe the key limitation of CNNs that attention mechanisms address. Explain, with the "birds in an image" example from the lecture, why a CNN would struggle and how attention helps.

---

**Q54. (Self-Attention Pipeline)**  
Describe the four main steps of computing self-attention as presented in Lecture 4:
1. Encode position information  
2. Extract Q, K, V  
3. Compute attention weights  
4. Extract features with high attention

Explain each step in 1–2 sentences.

---

**Q55. (Positional Encoding vs. CNN)**  
Why do transformers require positional encoding while CNNs do not? Contrast how each architecture handles spatial/positional information.

---

**Q56. (Synthetic Data)**  
(a) Give **two** advantages of synthetic data over real-world data for training CV models.  
(b) Name the two method categories for generating synthetic data from the lectures and briefly describe each.

---

---

## Answer Key

---

### Part A — Multiple Choice

| Q | Answer | Brief Explanation |
|---|--------|-------------------|
| Q1 | **C** | Shape is (Height, Width, Channels). 1080 rows, 1920 columns, 3 color channels. (Lecture 1, slide 15) |
| Q2 | **B** | OpenCV uses BGR; matplotlib expects RGB. Displaying without conversion swaps red and blue. (Lab 1, Part A.1) |
| Q3 | **B** | PNG supports an alpha (transparency) channel. JPEG does not. (Lecture 1, slide 18) |
| Q4 | **B** | MP4 is the container that holds video/audio/metadata; H.265 is the codec that compresses the video. (Lecture 1, slides 19–21) |
| Q5 | **C** | Object detection is an object-level task (bounding boxes + classes). Classification is image-level; depth estimation is pixel-level; action recognition is video-level. (Lecture 1, slide 24) |
| Q6 | **B** | Semantic segmentation labels every pixel by class without separating instances. Instance segmentation gives each object a unique mask. (Lecture 1, slides 29–31) |
| Q7 | **C** | Synthetic data gives scale, rare-event coverage, and control, but does not guarantee perfect real-world performance. (Lecture 1, slide 43) |
| Q8 | **B** | Physically based rendering uses 3D engines; generative methods use models like CycleGAN/diffusion. (Lecture 1, slide 44) |
| Q9 | **B** | Hubel & Wiesel discovered hierarchical processing in the cat visual cortex — simple cells → complex cells. (Lecture 2, slide 3) |
| Q10 | **B** | Deep learning automatically discovers feature representations from raw data, unlike hand-crafted features. (Lecture 2, slide 11) |
| Q11 | **B** | AlexNet succeeded due to ImageNet (big data), GPU compute, and algorithmic innovations (ReLU, Dropout, deep convolutions). (Lecture 2, slide 9) |
| Q12 | **B** | FCNs flatten images to 1-D, losing spatial structure and requiring too many parameters. (Lecture 2, slides 19–20) |
| Q13 | **B** | Filters operate locally and the same weights are reused at every spatial position (weight sharing). (Lecture 2, slide 32) |
| Q14 | **C** | The output of sliding a filter across an image is called a feature map. (Lecture 2, slides 27–28) |
| Q15 | **B** | ReLU: g(z) = max(0, z). Negative values become zero; positives unchanged. (Lecture 3, slide 10) |
| Q16 | **B** | Without non-linearity, stacking linear layers collapses into one linear operation. (Lecture 3, slide 10) |
| Q17 | **C** | Pooling has no learnable parameters; pool size and stride are fixed hyperparameters. (Lecture 3, slide 13) |
| Q18 | **B** | With padding=1, kernel=3, stride=1: output = (32+2-3)/1+1 = 32. Depth = 64 filters. (Lecture 3, slide 7) |
| Q19 | **B** | (28+0-3)/1+1 = 26. Output is 26 × 26. (Lecture 3, slide 7; Lab 2, Part B.2) |
| Q20 | **B** | Softmax converts logits into a probability distribution summing to 1 for classification. (Lecture 3, slide 19) |
| Q21 | **B** | Backbone = feature extraction (edges → textures → shapes); head = task-specific output (class scores). (Lecture 3, slide 24) |
| Q22 | **B** | R-CNN uses manually defined proposals; Faster R-CNN uses a learnable RPN sharing the same backbone features. (Lecture 3, slides 29–33) |
| Q23 | **C** | YOLO predicts everything in one forward pass — no separate region proposal step. (Lecture 3, slides 35–36) |
| Q24 | **B** | Early YOLO struggled with small objects and had less precise localization than two-stage detectors. (Lecture 3, slide 37) |
| Q25 | **B** | CNNs only model local neighborhoods; distant patches don't directly interact. (Lecture 4, slides 2–3) |
| Q26 | **B** | Q = what a token looks for; K = what a token offers; V = information shared based on attention. (Lecture 4, slides 10–12, 30) |
| Q27 | **B** | Attention score is the pairwise similarity (dot product) between Q and K. (Lecture 4, slides 19–22) |
| Q28 | **B** | Self-attention processes all tokens at once with no inherent order; positional encoding adds position info. (Lecture 4, slides 7, 14, 28) |
| Q29 | **B** | Different heads attend to different relationships in different learned subspaces. (Lecture 4, slides 25–27, 31) |
| Q30 | **B** | A token is a vector (embedding) representing an image patch — the fundamental unit for transformer processing. (Lecture 4, slide 9) |
| Q31 | **C** | PyTorch convention for batched images is (Batch, Channels, Height, Width). (Lab 1, Part B.1) |
| Q32 | **B** | IoU = intersection area / union area of predicted and ground-truth boxes. (Lab 2, Part C.1) |

### Part B — True / False

| Q | Answer | Justification |
|---|--------|---------------|
| Q33 | **True** | Grayscale images are 2-D arrays with values 0 (black) to 255 (white). (Lecture 1, slide 15) |
| Q34 | **False** | JPEG does not support transparency. PNG supports an alpha channel for transparency. (Lecture 1, slide 18) |
| Q35 | **True** | FPS = frames per second. 30 FPS means 30 individual image frames each second. (Lecture 1, slide 19) |
| Q36 | **True** | Traditional filters are hand-designed; CNN filters are learned via backpropagation during training. (Lecture 2, slides 30–31) |
| Q37 | **True** | Multiple linear operations compose into one linear operation. Non-linearity is essential to model complex patterns. (Lecture 3, slide 10) |
| Q38 | **True** | A filter's depth matches the input's channel depth. For RGB (3 channels), each filter is 3 × 3 × 3. (Lecture 2, slide 29; Lecture 3, slide 7) |
| Q39 | **True** | Each filter produces one feature map. 64 filters → 64 feature maps, forming the depth of the output volume. (Lecture 3, slide 7) |
| Q40 | **False** | Larger stride means the filter skips more positions, producing a *smaller* output feature map. (Lecture 3, slide 5) |
| Q41 | **True** | The receptive field is the input region affecting one output neuron. Deeper layers have larger effective receptive fields. (Lecture 3, slide 5) |
| Q42 | **True** | YOLO uses an S×S grid; each cell predicts bounding boxes (x,y,h,w), confidence P(object), and class probabilities. (Lecture 3, slide 36) |
| Q43 | **False** | Faster R-CNN is a two-stage detector (RPN + classifier). YOLO is a single-stage detector. (Lecture 3, slides 33–35) |
| Q44 | **False** | Different heads learn different attention patterns — each operates on a different learned subspace. (Lecture 4, slide 31) |
| Q45 | **True** | IoU ≥ 0.5 is the standard threshold for a detection to count as a True Positive. (Lab 2, Part C.1) |

### Part C — Short Answer (Model Answers)

---

**Q46.**  
A color image is a 3-D numerical array of shape (Height, Width, Channels). Each element in the array is a pixel with an intensity value (typically 0–255). For a color image, there are usually 3 channels — Red, Green, and Blue (RGB) — each representing one color component. Resolution refers to the number of rows (height) and columns (width) of pixels. A grayscale image has only one channel — a single 2-D array of intensity values — whereas a color image stacks three such arrays.

---

**Q47.**  
A video container (e.g., MP4, MKV, MOV) is a wrapper file format that holds the video stream, audio stream, and metadata (subtitles, chapters) together. A codec (e.g., H.264, H.265, AV1) is the algorithm that compresses and encodes the actual video data so that files are not enormous in size. Both are needed because the container organizes all the media components into one file, while the codec shrinks the video data to a manageable size with acceptable quality.

---

**Q48.**  
"Deep learning is representation learning" means that instead of relying on hand-crafted features designed by human experts (e.g., edge detectors, color histograms), deep neural networks automatically discover the data representations (features) needed for the task directly from raw data. In traditional ML, the quality of the system depends heavily on manual feature engineering. Deep networks learn hierarchical features — early layers detect simple patterns (edges), and deeper layers extract complex, abstract structures (shapes, objects). This approach requires large datasets because the network needs enough examples to learn meaningful patterns without being told what to look for.

---

**Q49.**  
An FCN requires flattening a 2-D image into a 1-D vector, which destroys all spatial relationships between pixels. It also has an extremely large number of parameters (e.g., a 256 × 256 × 3 image yields ~196K inputs, each connected to every neuron in the next layer). CNNs solve this through: (1) **local connectivity** — each neuron sees only a small spatial patch, preserving spatial structure; and (2) **weight sharing** — the same filter weights are reused across all spatial locations, dramatically reducing the parameter count and allowing the same feature to be detected anywhere in the image.

---

**Q50.**

| Layer | Output (H × W × D) | Explanation |
|-------|---------------------|-------------|
| Conv2d (k=3, s=1, p=1) | 32 × 32 × 32 | Padding=1 with kernel=3 preserves spatial size. Output depth = 32 (number of filters). |
| ReLU | 32 × 32 × 32 | Element-wise activation; no change in dimensions. |
| MaxPool2d (k=2, s=2) | 16 × 16 × 32 | Halves spatial dimensions. Depth unchanged. |

Only MaxPool changes the spatial resolution. Conv with padding=1 preserves it, and ReLU is element-wise.

---

**Q51.**  
A two-stage detector like Faster R-CNN operates in two steps: (1) a Region Proposal Network (RPN) generates candidate regions likely to contain objects, and (2) each proposed region is classified and its bounding box is refined. A single-stage detector like YOLO skips proposals entirely — it divides the image into a grid and predicts bounding boxes, confidence, and class probabilities directly in one forward pass. The trade-off: two-stage detectors tend to be more accurate (especially for small objects and precise localization) but slower; single-stage detectors are significantly faster and simpler, making them ideal for real-time applications like autonomous driving and surveillance.

---

**Q52.**  
(a) High precision (0.85) means most detections are correct (few false positives). Low recall (0.40) means the detector misses 60% of actual objects (many false negatives). The detector is conservative — when it detects something, it's usually right, but it fails to find most targets.

(b) This would **not** be acceptable for surveillance. Missing an intruder (false negative) is very dangerous, so high recall is critical. A recall of 0.40 means 60% of intruders go undetected.

(c) **mAP (mean Average Precision)** — specifically mAP@50 or mAP@50-95 — summarizes detection quality across all classes by computing the area under the precision-recall curve for each class and averaging.

---

**Q53.**  
CNNs build features from local patches using small convolution filters. Each filter has a limited receptive field, so early layers only see nearby pixels. Distant parts of the image (e.g., a bird in the top-right and a bird in the bottom-left) do not directly interact. To answer "Is the top-right bird the same species as the bottom-left bird?" the network would need to compare features from far-apart regions, but CNNs can only aggregate global information by stacking many layers — an indirect and inefficient process. Attention mechanisms solve this by computing pairwise relationships between **all** positions simultaneously, allowing any token to directly attend to any other token regardless of distance.

---

**Q54.**
1. **Encode position information:** Since all tokens are fed in at once, positional encodings are added to each token embedding so the model knows the spatial order/position of each token.
2. **Extract Q, K, V:** For each token, three vectors are computed via learned linear projections — the Query (what this token is looking for), the Key (what this token offers for matching), and the Value (the information to share).
3. **Compute attention weights:** Pairwise similarity scores are computed between each Query and all Keys (typically via dot product), then normalized (e.g., via softmax) to produce attention weights that indicate how relevant each token is.
4. **Extract features with high attention:** The attention weights are used to take a weighted sum of the Value vectors, producing a new representation for each token that incorporates information from the most relevant other tokens.

---

**Q55.**  
Transformers process all input tokens **simultaneously** via self-attention, which computes pairwise relationships regardless of position. This means the architecture has no built-in awareness of order — swapping two tokens would produce identical attention scores without positional encoding. Positional encoding is added to each token to inject position information. CNNs, by contrast, inherently preserve spatial structure through **local connectivity**: convolution filters operate on specific spatial neighborhoods, and a feature's location in the feature map directly reflects its position in the input. No explicit position encoding is needed because locality is built into the architecture.

---

**Q56.**  
(a) Two advantages: (1) **Scale** — millions of perfectly labeled frames (bounding boxes, masks, depth, etc.) can be generated automatically, while real-world labeling is expensive and slow. (2) **Coverage of rare events** — synthetic data can generate edge cases (unusual weather, lighting, rare objects) that are difficult, dangerous, or impossible to collect in the real world.

(b) Two categories: (1) **Physically Based Rendering** (e.g., Blender, Unreal Engine, Omniverse) — creates photorealistic images from 3D scenes with full control over geometry, lighting, and camera, producing pixel-perfect ground-truth labels. (2) **Generative Methods** (e.g., CycleGAN, pix2pix, diffusion models) — data-driven approaches that learn to generate realistic images from existing data, easier to scale but require substantial real data to train.

---

*Good luck studying!*