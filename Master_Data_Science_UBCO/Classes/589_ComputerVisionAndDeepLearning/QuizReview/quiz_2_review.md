# DATA 589 — Applied Computer Vision and Deep Learning
# Quiz 2 — Practice Questions
### UBCO Master of Data Science

---

> **Purpose:** These practice questions help you prepare for Quiz 2. They cover the **style, format, and difficulty level** you can expect. The actual quiz may cover any topic from Lectures 4–7 and Labs 3–4.
>
> **Topics to study:**
> - CNN limitations (locality, no long-range dependencies)
> - Attention mechanism: intuition, query/key/value, self-attention
> - Self-attention computation: Q, K, V projections, attention scores ($QK^T / \sqrt{d_k}$), softmax, weighted sum
> - 1×1 convolution as channel-mixing linear projection
> - Multi-head self-attention: multiple subspaces, different relationship types
> - Transformer encoder: MSA + MLP + residual connections + LayerNorm
> - Vision Transformer (ViT): patch embeddings, positional embeddings, CLS token, classification head
> - ViT model variants (ViT-Base, ViT-Large) and DETR for detection
> - Self-supervised learning: pretext tasks vs. downstream tasks
> - MAE: masked image prediction, encoder efficiency
> - DINO: teacher–student self-distillation, EMA, attention maps
> - Foundation models: definition, properties, adaptability
> - Linear probing vs. full fine-tuning
> - Contrastive learning and CLIP: image–text alignment, similarity matrix, CLIP loss
> - Zero-shot classification: concept, how CLIP enables it, limitations, prompt sensitivity
> - Generative models: density estimation vs. sample generation
> - Autoencoders: encoder–decoder, bottleneck, reconstruction loss
> - VAEs: probabilistic latent space, $\mu$ and $\sigma$, KL divergence, latent perturbation
> - GANs: generator vs. discriminator, adversarial minimax game, CycleGAN, Pix2Pix
> - Diffusion models: forward (noising) and reverse (denoising), DDPM, latent diffusion, ControlNet
> - Comparison of AE, VAE, GAN, and diffusion models
> - Practical lab concepts: ViT classification, DETR detection, SegFormer segmentation, CLIP zero-shot, DINOv2 linear probing, image–text retrieval
>
> **Tip:** Focus on *understanding concepts*, not memorizing code syntax or PyTorch function signatures.

---

## Part A — Multiple Choice

*Select the single best answer for each question.*

---

### Lecture 4 Topics: CNN Limitations, Attention Mechanism

---

**Q1.** What is the **primary limitation of CNNs** that motivates the introduction of attention?

A. CNNs cannot learn any visual patterns  
B. CNNs process local patches only and have no direct mechanism to model long-range dependencies between distant image regions  
C. CNNs require more data than any other architecture  
D. CNNs cannot be trained with GPUs  

---

**Q2.** In the attention mechanism, what do the **Query (Q)**, **Key (K)**, and **Value (V)** represent?

A. Q compresses the input, K stores the gradients, V stores the loss  
B. Q represents what a token is *looking for*, K represents what a token *offers* for matching, and V represents the *information* that will be shared based on attention weights  
C. Q, K, and V are three independent neural networks that operate in sequence  
D. Q is the input image, K is the label, and V is the prediction  

---

**Q3.** In self-attention, the attention score between two tokens is computed by:

A. Subtracting the Query from the Value  
B. Computing the pairwise similarity (e.g., dot product) between the Query and Key vectors, then scaling by $\sqrt{d_k}$ and applying softmax  
C. Averaging all token embeddings  
D. Applying max pooling over the Value vectors  

---

**Q4.** Why do Transformers need **positional encoding** while CNNs do not?

A. Because Transformers process tokens sequentially like RNNs  
B. Because self-attention processes all tokens simultaneously with no inherent notion of order; CNNs preserve spatial information through local connectivity  
C. Because positional encoding reduces model parameters  
D. Because positional encoding replaces the Value vectors  

---

### Lecture 5 Topics: Self-Attention for Images, Multi-Head Attention, ViT, DETR

---

**Q5.** What does a **1×1 convolution** do in the context of self-attention?

A. Extracts spatial patterns across a 1×1 neighborhood  
B. Reduces image size by half  
C. Mixes information across channels only (acts as a per-pixel linear layer)  
D. Applies spatial pooling  

---

**Q6.** Given an input of $n = 9$ tokens with feature dimension $d = 3$, the attention score matrix $QK^T$ has shape:

A. 3 × 3  
B. 9 × 3  
C. 9 × 9  
D. 3 × 9  

---

**Q7.** In **multi-head self-attention**, what is the purpose of using multiple heads?

A. All heads learn the same attention pattern for robustness  
B. Different heads can learn different types of relationships — one may focus on local structure while another captures long-range interactions  
C. Multiple heads are used only to increase the number of parameters  
D. Each head processes a different image in the batch  

---

**Q8.** In the Transformer encoder, what is the role of the **residual connection** (Add & Norm)?

A. It replaces the attention computation  
B. It stabilizes training, preserves information, and helps gradients flow by adding the original input back to the layer's output  
C. It reduces the number of tokens  
D. It computes the positional encoding  

---

**Q9.** In the Transformer encoder, why is the **MLP (feed-forward network)** needed in addition to self-attention?

A. It replaces self-attention in deeper layers  
B. Self-attention mixes information *between* tokens; the MLP transforms features *within* each token, adding non-linear expressiveness  
C. The MLP is optional and has no effect on performance  
D. It computes the positional encoding for the next layer  

---

**Q10.** In ViT, a 224 × 224 RGB image is divided into 16 × 16 non-overlapping patches. Each patch embedding has dimension 768. What is the shape of the patch embedding matrix (before adding the CLS token)?

A. 196 × 768  
B. 768 × 196  
C. 224 × 224  
D. 16 × 16 × 3  

---

**Q11.** Why is the patch embedding in ViT **NOT** just flattening?

A. Because it reduces image size  
B. Because it normalizes the data  
C. Because it is a learnable projection using convolution filters (Conv2d with kernel=16, stride=16) that extracts features from each patch  
D. Because it removes color channels  

---

**Q12.** What is the purpose of the **[CLS] token** in ViT?

A. It stores the loss value  
B. It is a learnable token prepended to the sequence that collects information from all patches via self-attention and is used for final classification  
C. It replaces the positional encoding  
D. It is a padding token for shorter sequences  

---

**Q13.** The ViT classification head works by:

A. Averaging all 196 patch embeddings and passing through an MLP  
B. Taking the final [CLS] token representation and feeding it through an MLP to produce class scores  
C. Applying a convolution over all tokens  
D. Using the positional embedding as the class prediction  

---

**Q14.** What is the key innovation of **DETR** compared to traditional detectors (Faster R-CNN, YOLO)?

A. It uses a single convolutional layer for detection  
B. It uses learned **object queries** and a Transformer decoder, eliminating anchors, NMS, and region proposals for a fully end-to-end pipeline  
C. It uses larger images than other detectors  
D. It only detects one object per image  

---

**Q15.** In DETR, what happens to **unused object queries** when there are fewer objects than queries (e.g., 3 objects but 100 queries)?

A. They are removed from the model  
B. They predict "no object" — the model learns that unused queries should output the "no object" class  
C. They are recycled for the next image  
D. They produce duplicate predictions that must be filtered by NMS  

---

### Lecture 6 Topics: Self-Supervised Learning, MAE, DINO, Foundation Models, CLIP

---

**Q16.** Which statement best describes **self-supervised learning**?

A. The model always requires a large labeled dataset  
B. The model learns only from random noise  
C. The data itself provides the target for learning — no manual labels are required  
D. The model can only be used for classification  

---

**Q17.** What is a **pretext task** in self-supervised learning?

A. The final task the model is deployed for (e.g., classification)  
B. A task automatically defined from the data itself (e.g., predicting masked patches, predicting rotation) that helps the model learn useful representations  
C. A task that requires manually labeled data  
D. The same as a downstream task  

---

**Q18.** In **MAE**, what is the model mainly trained to do during pretraining?

A. Predict bounding boxes for objects  
B. Reconstruct missing image patches from the visible ones  
C. Match image embeddings to text captions  
D. Classify images into fixed labeled categories  

---

**Q19.** In **DINO**, the **student** and **teacher** networks receive:

A. The same identical crop of the image  
B. Different augmented views (crops) of the same image; the student learns to match the teacher's output distribution  
C. Images from completely different datasets  
D. Only text data  

---

**Q20.** What is the main purpose of **linear probing** after self-supervised pretraining?

A. To generate captions for unlabeled images  
B. To evaluate whether the pretrained encoder learned useful features by training only a linear layer on labeled data  
C. To replace the encoder with a larger model  
D. To train the model from scratch on a new dataset  

---

**Q21.** What makes a model a **foundation model**?

A. It is only used for one specific task  
B. It must be retrained from scratch for every new task  
C. It is trained on large-scale data to learn general-purpose representations that can be adapted to many downstream tasks  
D. It only works with text  

---

**Q22.** How does CLIP's training differ from DINO's training?

A. CLIP uses only images; DINO uses image–text pairs  
B. CLIP learns from image–text pairs using contrastive learning; DINO learns from images alone using teacher–student self-distillation  
C. CLIP and DINO use identical training procedures  
D. DINO requires manual labels; CLIP does not  

---

**Q23.** In CLIP's contrastive training, the similarity matrix is $N \times N$ where $N$ is the batch size. What does the **diagonal** of this matrix represent?

A. The loss gradients  
B. The correct (matched) image–text pairs — these should have the highest similarity  
C. The model's confidence scores  
D. The learning rate schedule  

---

**Q24.** Which statement about **zero-shot CLIP** is correct?

A. It requires fine-tuning on the target classes before inference  
B. It uses a fixed classifier that must be retrained for new classes  
C. It predicts classes by comparing image embeddings with text prompt embeddings — no task-specific training required  
D. It is the same thing as linear probing  

---

**Q25.** Which of the following is a known **limitation of zero-shot CLIP**?

A. It cannot process images  
B. It is sensitive to prompt phrasing, inherits biases from internet-scale training data, and struggles with fine-grained recognition and domain shift  
C. It always outperforms supervised methods  
D. It requires GPU training for every new query  

---

### Lecture 7 Topics: Generative Models — AE, VAE, GAN, Diffusion

---

**Q26.** What is the main goal of a **generative model**?

A. To predict labels from input data  
B. To compress data into smaller vectors only  
C. To learn the underlying data distribution $p(x)$ and generate new samples  
D. To remove the need for neural networks  

---

**Q27.** Why is the **bottleneck** important in an autoencoder?

A. It makes the model train faster by increasing parameters  
B. It forces the model to compress information and learn meaningful features in the latent space  
C. It guarantees that the model becomes probabilistic  
D. It replaces the decoder during inference  

---

**Q28.** What is the key difference between a standard **autoencoder** and a **VAE**?

A. They are identical  
B. An autoencoder maps input to a single deterministic latent point; a VAE maps input to a probability distribution ($\mu$, $\sigma$) and samples from it, enabling generation  
C. A VAE has no decoder  
D. An autoencoder uses adversarial training  

---

**Q29.** In a VAE, the loss function consists of two terms. What are they?

A. Cross-entropy loss and IoU loss  
B. Reconstruction loss (how well the decoder reproduces the input) and KL divergence (regularizing the latent distribution to be close to a standard Gaussian)  
C. Generator loss and discriminator loss  
D. Forward loss and reverse loss  

---

**Q30.** What is the main idea behind **GAN training**?

A. The encoder compresses the image into a latent vector  
B. The model learns by minimizing only reconstruction loss  
C. Noise is gradually added and then removed step by step  
D. A generator and discriminator compete in an adversarial minimax game — the generator tries to produce realistic samples and the discriminator tries to distinguish real from fake  

---

**Q31.** What is **CycleGAN** used for?

A. Classifying images into categories  
B. Unpaired image-to-image translation / style transfer between two domains without requiring paired training data  
C. Object detection in videos  
D. Compressing images into latent codes  

---

**Q32.** What is the **core idea** behind diffusion models?

A. A generator and discriminator compete  
B. The model learns a deterministic mapping from input to output  
C. The model learns to reverse a gradual noising process — noise is added step by step during training, and the model learns to denoise step by step during generation  
D. The model predicts image rotations  

---

**Q33.** Compared to GANs, what is a **strength** and a **weakness** of diffusion models?

A. Strength: faster inference. Weakness: lower quality  
B. Strength: more stable training and higher sample quality/diversity. Weakness: slower inference due to iterative denoising  
C. Strength: no training needed. Weakness: requires labels  
D. Strength and weakness are identical to GANs  

---

**Q34.** What does **Latent Diffusion** (used in Stable Diffusion) do differently from standard pixel-space diffusion?

A. It applies diffusion in a compressed latent space (produced by a VAE encoder), which is much more computationally efficient than diffusing full-resolution images  
B. It uses a GAN instead of denoising  
C. It operates only on text, not images  
D. It removes the need for a neural network  

---

### Lab-Specific Topics

---

**Q35.** In Lab 3, you used **ViT** for classification, **DETR** for detection, and **SegFormer** for segmentation. Which of the following is true about SegFormer?

A. SegFormer uses a single-scale transformer like ViT  
B. SegFormer uses a hierarchical transformer with multiple stages of decreasing spatial resolution, replacing the CNN encoder in traditional segmentation models  
C. SegFormer cannot produce per-pixel predictions  
D. SegFormer requires anchors and NMS  

---

**Q36.** In Lab 4, you compared **CLIP zero-shot** and **DINOv2 linear probing** on CIFAR-10. Which statement is most likely true?

A. CLIP zero-shot always outperforms DINOv2 linear probing  
B. DINOv2 linear probing typically achieves higher accuracy because it trains on task-specific labeled data, while CLIP zero-shot does not use any labeled data at inference  
C. Both methods achieve identical accuracy  
D. Neither method can classify CIFAR-10 images  

---

**Q37.** In Lab 4, the **image–text similarity matrix** computed with CLIP shows:

A. The pixel-wise difference between images  
B. The cosine similarity between CLIP image embeddings and text embeddings — diagonal entries should be high for correct matches  
C. The training loss for each sample  
D. The attention weights from the transformer  

---

---

## Part B — True or False

*State whether the statement is True or False, and provide a one-sentence justification.*

---

**Q38.** Self-attention has no inherent notion of token order — without positional encoding, swapping two tokens would produce identical attention scores.

True / False  
Justification: ___________

---

**Q39.** In multi-head self-attention, all heads are forced to learn the same attention pattern.

True / False  
Justification: ___________

---

**Q40.** The patch embedding in ViT is created using a learnable Conv2d projection (kernel=16, stride=16), not simple flattening.

True / False  
Justification: ___________

---

**Q41.** DETR uses Non-Maximum Suppression (NMS) to remove duplicate detections.

True / False  
Justification: ___________

---

**Q42.** In DINO, the teacher network is trained using standard backpropagation with gradient descent.

True / False  
Justification: ___________

---

**Q43.** CLIP's zero-shot classification requires no labeled data or task-specific training — classes are defined at inference time using text prompts.

True / False  
Justification: ___________

---

**Q44.** A standard autoencoder can generate diverse new samples by sampling random points in its latent space.

True / False  
Justification: ___________

---

**Q45.** In VAEs, varying one latent dimension while keeping others fixed produces smooth transitions in the generated output.

True / False  
Justification: ___________

---

**Q46.** In GAN training, the generator and discriminator cooperate toward the same objective.

True / False  
Justification: ___________

---

**Q47.** Diffusion models generate images in a single forward pass, just like GANs.

True / False  
Justification: ___________

---

**Q48.** Linear probing requires freezing the pretrained encoder and training only a linear classifier on labeled data.

True / False  
Justification: ___________

---

**Q49.** In CLIP, the contrastive loss is applied in only one direction — image to text.

True / False  
Justification: ___________

---

---

## Part C — Short Answer / Explanation

*Write concise, precise answers. Aim for 3–6 sentences per question.*

---

**Q50. (CNN vs Transformer)**  
Explain the fundamental difference between how a CNN and a Vision Transformer (ViT) capture spatial relationships. Use the "two birds in an image" example from Lecture 4 to illustrate the CNN limitation and how attention solves it.

---

**Q51. (Self-Attention Computation)**  
Given an input $X \in \mathbb{R}^{9 \times 3}$ (9 tokens, each with 3-dimensional features):
(a) What are the dimensions of $Q$, $K$, and $V$ (assuming $d_q = d_k = d_v = 3$)?  
(b) What is the shape of the attention score matrix $QK^T$?  
(c) What does each row of the attention map (after softmax) represent?

---

**Q52. (ViT Architecture)**  
Describe the full ViT pipeline for classifying a 224 × 224 RGB image. Include: (1) how patches are created and embedded, (2) the role of positional embeddings and the CLS token, (3) the Transformer encoder processing, and (4) how the final class prediction is made.

---

**Q53. (MAE vs DINO)**  
Compare MAE and DINO as self-supervised learning methods. For each, describe: (a) the pretext task, (b) how the training signal is generated, and (c) one key advantage. When might you prefer MAE over DINO?

---

**Q54. (CLIP and Zero-Shot)**  
(a) Explain how CLIP is trained — what is the training data, what is the objective, and how is the loss computed?  
(b) Why does this training procedure enable zero-shot classification?  
(c) Name two limitations of zero-shot CLIP.

---

**Q55. (Generative Models Comparison)**  
Complete the following table:

| Model | Can generate new samples? | How it generates | Key strength | Key weakness |
|-------|--------------------------|-----------------|-------------|-------------|
| Autoencoder | X | X | X | X |
| VAE | X | X | X | X |
| GAN | X | X | X | X |
| Diffusion | X | X | X | X |

---

**Q56. (Scenario: Real-World System Design)**  
You are designing a quality inspection system for a factory. The system must classify defects into categories, but new defect types appear occasionally. You have limited labeled data.

(a) Would you use CLIP zero-shot, DINOv2 + linear probing, or full fine-tuning? Justify your choice.  
(b) How would you handle the appearance of a completely new defect type?  
(c) What is one risk of using a foundation model trained on internet data for an industrial domain?

---

---

## Answer Key

---

### Part A — Multiple Choice

| Q | Answer | Brief Explanation |
|---|--------|-------------------|
| Q1 | **B** | CNNs rely on local receptive fields; distant patches do not directly interact. (Lecture 4, slides 2–3) |
| Q2 | **B** | Q = what a token looks for; K = what it offers; V = information shared based on attention weights. (Lecture 4, slides 10–12, 30) |
| Q3 | **B** | Attention scores: $QK^T / \sqrt{d_k}$, then softmax to normalize. (Lecture 5, slides 7–8) |
| Q4 | **B** | Self-attention processes all tokens at once with no inherent order; positional encoding injects position info. CNNs use local filters with fixed spatial connectivity. (Lecture 4, slides 7, 14; Lecture 5) |
| Q5 | **C** | A 1×1 convolution is a per-pixel linear layer that mixes channels, not spatial locations. (Lecture 5, slide 13) |
| Q6 | **C** | $Q \in \mathbb{R}^{9\times3}$, $K^T \in \mathbb{R}^{3\times9}$. Product: $9 \times 3 \cdot 3 \times 9 = 9 \times 9$. (Lecture 5, slide 7) |
| Q7 | **B** | Different heads attend to different relationships in different learned subspaces. (Lecture 5, slides 14–16) |
| Q8 | **B** | Residual connections add the original input back, stabilizing training and helping gradients flow. (Lecture 5, slide 20) |
| Q9 | **B** | Attention mixes tokens; MLP transforms within each token independently, adding non-linearity. (Lecture 5, slides 20–21) |
| Q10 | **A** | 14 × 14 = 196 patches, each projected to 768 dims → 196 × 768. (Lecture 5, slides 26–28) |
| Q11 | **C** | ViT uses Conv2d(3, 768, kernel_size=16, stride=16) — a learnable feature extraction, not just flattening. (Lecture 5, slide 28) |
| Q12 | **B** | CLS token aggregates information from all patches via self-attention; used for classification. (Lecture 5, slides 30–31) |
| Q13 | **B** | The final CLS token is fed through an MLP to produce class scores. (Lecture 5, slide 31) |
| Q14 | **B** | DETR uses object queries + Transformer, eliminating anchors and NMS. (Lecture 5, slides 36–39) |
| Q15 | **B** | Unused object queries predict "no object" class via bipartite matching. (Lecture 5, slides 38–39; Lab 3) |
| Q16 | **C** | Self-supervised learning uses the data itself as the learning signal, no manual labels needed. (Lecture 6, slides 4–7) |
| Q17 | **B** | A pretext task is automatically defined from data (e.g., masked patch prediction), used to learn representations without labels. (Lecture 6, slides 6–9) |
| Q18 | **B** | MAE reconstructs missing image patches from visible ones. (Lecture 6, slides 14–15) |
| Q19 | **B** | Student and teacher receive different augmented views; student learns to match teacher's output. (Lecture 6, slides 23–24) |
| Q20 | **B** | Linear probing evaluates representation quality by training only a linear classifier. (Lecture 6, slide 17) |
| Q21 | **C** | Foundation models are trained on large-scale data for general representations, adaptable to many tasks. (Lecture 6, slide 26) |
| Q22 | **B** | CLIP uses image–text contrastive learning; DINO uses images-only teacher–student self-distillation. (Lecture 6, slides 24, 28–31) |
| Q23 | **B** | Diagonal entries are correct image–text pairs — these should have highest similarity. (Lecture 6, slides 32–33) |
| Q24 | **C** | CLIP compares image embeddings with text prompt embeddings; no fine-tuning needed. (Lecture 6, slides 37–42, 45) |
| Q25 | **B** | CLIP has prompt sensitivity, dataset bias, domain shift issues, and struggles with fine-grained recognition. (Lecture 6, slide 43) |
| Q26 | **C** | Generative models learn $p(x)$ to generate new samples. (Lecture 7, slides 4–5) |
| Q27 | **B** | The bottleneck forces compression, requiring the model to learn meaningful latent features. (Lecture 7, slide 16) |
| Q28 | **B** | AE: deterministic latent point. VAE: distribution ($\mu$, $\sigma$) enabling sampling and generation. (Lecture 7, slides 19–22) |
| Q29 | **B** | VAE loss = reconstruction + KL divergence (regularizing latent space to $\mathcal{N}(0,1)$). (Lecture 7, slides 24–26) |
| Q30 | **D** | GAN: generator vs. discriminator in a minimax game. (Lecture 7, slides 31–33) |
| Q31 | **B** | CycleGAN does unpaired image-to-image translation / style transfer. (Lecture 7, slides 36–37) |
| Q32 | **C** | Diffusion: learn to reverse gradual noising. (Lecture 7, slides 42–44) |
| Q33 | **B** | Diffusion: stable training, high quality. Weakness: slow iterative inference. (Lecture 7, slides 43, 45) |
| Q34 | **A** | Latent diffusion applies diffusion in VAE's compressed latent space, much cheaper computationally. (Lecture 7, slide 47) |
| Q35 | **B** | SegFormer uses a hierarchical multi-stage transformer. (Lab 3, Part E) |
| Q36 | **B** | DINOv2 linear probe typically achieves higher accuracy on CIFAR-10 because it uses task-specific labeled data. (Lab 4, Parts E–F) |
| Q37 | **B** | The similarity matrix shows cosine similarity between image and text embeddings; diagonal = correct matches. (Lab 4, Part D) |

### Part B — True / False

| Q | Answer | Justification |
|---|--------|---------------|
| Q38 | **True** | Self-attention computes pairwise similarities regardless of position; without positional encoding, token order is lost. (Lecture 4, slide 14; Lecture 5) |
| Q39 | **False** | Different heads learn different attention patterns — each operates on a different learned subspace. (Lecture 5, slides 14–15) |
| Q40 | **True** | ViT uses nn.Conv2d(3, 768, kernel_size=16, stride=16) — a learnable projection, not simple flattening. (Lecture 5, slide 28) |
| Q41 | **False** | DETR does NOT use NMS. It uses bipartite matching between predictions and ground truth. Unused queries predict "no object." (Lecture 5, slides 36–39) |
| Q42 | **False** | The DINO teacher is updated via EMA (Exponential Moving Average) of the student's weights — not via backpropagation. (Lecture 6, slide 24) |
| Q43 | **True** | CLIP zero-shot uses text prompts at inference time — no labeled data or task-specific training needed. (Lecture 6, slides 37–42, 45) |
| Q44 | **False** | A standard autoencoder has a deterministic, unregularized latent space — random sampling produces poor results. VAEs solve this by regularizing the latent space. (Lecture 7, slides 13–15, 19–22) |
| Q45 | **True** | VAE latent dimensions encode interpretable factors; varying one smoothly changes the corresponding visual attribute. (Lecture 7, slide 27) |
| Q46 | **False** | G and D compete adversarially — G tries to fool D, D tries to detect fakes. This is a minimax game, not cooperation. (Lecture 7, slides 31–33) |
| Q47 | **False** | Diffusion models require many iterative denoising steps to generate an image, unlike GANs which generate in one pass. (Lecture 7, slides 44–45) |
| Q48 | **True** | Linear probing freezes the encoder and trains only a linear layer to evaluate representation quality. (Lecture 6, slide 17; Lab 4, Part E) |
| Q49 | **False** | CLIP's contrastive loss is symmetric: image-to-text + text-to-image, averaged: $L = (L_m + L_t) / 2$. (Lecture 6, slides 34–36) |

### Part C — Short Answer (Model Answers)

---

**Q50.**  
CNNs use local convolution filters (e.g., 3×3) that connect each neuron to only its immediate spatial neighbours. Long-range dependencies require stacking many layers, and even then, the effective receptive field grows slowly. In the "two birds" example from Lecture 4, a bird in the top-right and a bird in the bottom-left do not directly interact because no single neuron is connected to both — they are too far apart for the local filters to bridge. In contrast, a Vision Transformer applies self-attention where every token interacts with every other token at each layer, regardless of distance. The model can directly compare the top-right bird patch with the bottom-left bird patch in a single layer, efficiently capturing long-range dependencies.

---

**Q51.**  
(a) $Q, K, V \in \mathbb{R}^{9 \times 3}$ — each of the 9 tokens gets a Query, Key, and Value vector of dimension 3.

(b) $QK^T \in \mathbb{R}^{9 \times 9}$ — entry $(i, j)$ is the similarity between token $i$'s Query and token $j$'s Key.

(c) Each row of the attention map (after softmax) represents how one token distributes its "attention budget" across all 9 tokens. The values sum to 1, indicating the relative importance of each other token when computing that token's updated representation.

---

**Q52.**  
(1) The 224 × 224 × 3 image is divided into 14 × 14 = 196 non-overlapping patches of size 16 × 16 × 3. Each patch is projected to a 768-dimensional embedding using a learnable Conv2d(3, 768, kernel=16, stride=16) — this is NOT flattening but a learned projection.

(2) A learnable [CLS] token is prepended to the sequence, giving 197 tokens. Learnable positional embeddings are added to all 197 tokens so the model knows the spatial position of each patch.

(3) The 197 tokens pass through $L$ Transformer encoder blocks (e.g., 12 for ViT-Base). Each block consists of: LayerNorm → Multi-Head Self-Attention → Residual → LayerNorm → MLP → Residual.

(4) After all encoder blocks, the final representation of the [CLS] token is extracted and passed through an MLP classification head to produce class logits.

---

**Q53.**  
**MAE:** (a) Masked image prediction — randomly mask 75% of patches and reconstruct them. (b) Training signal is the pixel-level reconstruction error between predicted and actual masked patches. (c) Key advantage: encoder processes only 25% of patches, making pretraining very computationally efficient.

**DINO:** (a) Teacher–student self-distillation — student matches teacher's output on different augmented views. (b) Training signal comes from the teacher's output distribution (teacher updated via EMA, not backprop). (c) Key advantage: CLS token learns strong semantic features that produce attention maps resembling object segmentation — excellent for dense prediction tasks.

Prefer MAE when pretraining budget is limited (more efficient), or prefer DINO when you need strong semantic/spatial representations for detection and segmentation.

---

**Q54.**  
(a) CLIP is trained on 400M image–text pairs from the internet. For each batch of $N$ pairs, it encodes all images and all texts, computes an $N × N$ cosine similarity matrix, and applies symmetric cross-entropy loss: each image should match its correct caption (image-to-text direction) and each caption should match its correct image (text-to-image direction). The final loss averages both directions.

(b) This training creates a shared embedding space where images and text with similar meaning are close. At inference, we encode new class names as text prompts and compare them with image embeddings — whichever text prompt is closest is the predicted class. No retraining is needed because the model understands general visual-language relationships.

(c) Two limitations: (1) **Prompt sensitivity** — small wording changes can significantly affect accuracy. (2) **Dataset bias** — internet training data contains cultural/social biases that can lead to unfair or harmful predictions.

---

**Q55.**

| Model | Can generate? | How it generates | Key strength | Key weakness |
|-------|--------------|-----------------|-------------|-------------|
| Autoencoder | Not well | Deterministic encode–decode; latent space not regularized | Simple; learns useful compressed representations | Cannot generate diverse new samples; unstructured latent space |
| VAE | Yes | Samples $z$ from learned distribution $\mathcal{N}(\mu, \sigma^2)$, then decodes | Structured latent space; probabilistic; smooth interpolation | Outputs tend to be blurry |
| GAN | Yes | Generator transforms random noise into images; trained adversarially against a discriminator | Sharp, visually realistic outputs | Training instability; mode collapse |
| Diffusion | Yes | Starts from random noise; iteratively denoises over many steps | Highest sample quality and diversity; stable training | Slow inference (many denoising steps) |

---

**Q56.**  
(a) **CLIP zero-shot** would be a reasonable starting point since new defect types appear occasionally and you have limited labeled data. However, the **best practical choice** might be **DINOv2 + linear probing** for known categories (since it achieves higher accuracy with little labeled data) combined with CLIP zero-shot for detecting unknown/new defect types. If compute allows, full fine-tuning would give the best accuracy but requires the most labeled data and retraining effort.

(b) For a completely new defect type: use CLIP zero-shot by defining a text prompt for the new defect (e.g., "a photo of a scratch defect"). If zero-shot accuracy is insufficient, collect a small number of labeled examples and retrain the linear probe to include the new class.

(c) One key risk is **domain shift** — foundation models trained on internet images may not perform well on highly specialized industrial imagery (unusual textures, lighting, materials) that differs significantly from natural photographs. The model may produce overconfident incorrect predictions on out-of-distribution factory images.

---

*Good luck studying!*
