# bench: screen triage vs. pool order (LitSearch)

- questions: 597 (ALL LitSearch questions; raw family only — the frozen planner cache exists only for the engineered sample)
- sources: arxiv, semantic_scholar, openalex, crossref × depth 20 · cell arms: raw only — the NL question is the sole query; the frozen planner cache covers only the engineered 15-question sample
- semantic model: BAAI/bge-base-en-v1.5
- driver7 arm: off

## arm → candidate pool (READ THIS BEFORE QUOTING A DELTA)

| arm | candidate set |
|---|---|
| firstwins | agent+raw seat-quota pool (30 seats, 2-family baseline — NOT the shipped 7-family search) |
| screen_lex / screen_full / sem_only | the SAME quota pool, re-ordered |
| rrf_global | union of all query×source cells |
| screen_union | the SAME union, re-ordered |
| driver7 | the repo's recall leg end-to-end (opt-in) |

So `firstwins` vs `screen_full` is same-pool; `rrf_global` vs `screen_union` is same-union; `firstwins` vs `screen_union` is a DIFFERENT-pool comparison (the union is larger). The 0.2.0 headline used that cross-pool pair.

| arm | pool | gold in pool % | R@5 | R@10 | R@20 | MRR@100 |
|---|---|---|---|---|---|---|
| firstwins | agent+raw seat-quota pool (2-family baseline; not the shipped 7-family search) | 14.6 | 0.069 | 0.094 | 0.118 | 0.046 |
| rrf_global | union of all query×source cells | 16.8 | 0.069 | 0.094 | 0.118 | 0.047 |
| screen_lex | same quota pool | 14.6 | 0.116 | 0.134 | 0.139 | 0.082 |
| screen_full | same quota pool | 14.6 | 0.132 | 0.137 | 0.141 | 0.117 |
| sem_only | same quota pool | 14.6 | 0.132 | 0.142 | 0.142 | 0.109 |
| screen_union | same union | 16.8 | 0.147 | 0.154 | 0.161 | 0.124 |

## uncertainty (95% Wilson interval; n is tiny — do not over-read)

- **firstwins**: R@5 0.069 [0.052, 0.094] · R@20 0.118 [0.097, 0.149]
- **rrf_global**: R@5 0.069 [0.052, 0.094] · R@20 0.118 [0.097, 0.149]
- **screen_lex**: R@5 0.116 [0.095, 0.147] · R@20 0.139 [0.117, 0.173]
- **screen_full**: R@5 0.132 [0.111, 0.165] · R@20 0.141 [0.118, 0.174]
- **sem_only**: R@5 0.132 [0.111, 0.165] · R@20 0.142 [0.12, 0.176]
- **screen_union**: R@5 0.147 [0.124, 0.182] · R@20 0.161 [0.138, 0.198]

## paired comparisons (exact McNemar on hits; bootstrap on deltas)

| A → B | pooling | ΔR@5 [95%] | ΔR@20 [95%] | ΔMRR [95%] | McNemar R@20 p |
|---|---|---|---|---|---|
| firstwins → screen_union | DIFFERENT pools | 0.079 [0.057, 0.101] | 0.043 [0.027, 0.06] | 0.078 [0.06, 0.098] | b=27, c=0, p=0.0 |
| rrf_global → screen_union | same-pool | 0.079 [0.057, 0.101] | 0.043 [0.027, 0.06] | 0.078 [0.059, 0.097] | b=27, c=0, p=0.0 |
| firstwins → screen_full | same-pool | 0.064 [0.044, 0.085] | 0.023 [0.012, 0.035] | 0.071 [0.053, 0.091] | b=14, c=0, p=0.0001 |

A bootstrap interval that crosses 0 (or a McNemar p above 0.05) means the delta is not established at this sample size. The interval is the honest statement, not the point estimate.

## caveats

1. RAW family only: the natural-language question itself is the sole query — no planner, no concept blocks. Absolute recall is therefore a LOWER bound on what the shipped workflow (agent-crafted queries) reaches; it isolates the no-LLM ordering lever, not the product.
2. The cell arms use only the raw family of the seven shipped families; the driver7 arm is the end-to-end check (and is costly).
3. n=597 with ~1 gold/question; per-question ranks are in the table below and in the JSON so nothing is hidden.
4. The thresholds/bands are not tuned here: the lever under test is the ORDER, not the cutoffs.

## per question (gold first-rank; – = not in pool)

| set | question (60c) | pool | firstwins | rrf | lex | full | sem | union |
|---|---|---|---|---|---|---|---|---|
| inline_acl | Are there any research papers on methods to compress large-s | 30 | – | – | – | – | – | – |
| inline_acl | Are there any resources available for translating Tunisian A | 30 | – | – | – | – | – | – |
| inline_acl | Are there any studies that explore post-hoc techniques for h | 30 | 15 | 15 | 1 | 1 | 1 | 1 |
| inline_acl | Are there any tools or studies that have focused on building | 30 | – | – | – | – | – | – |
| inline_acl | Are there papers that propose contextualized calibration for | 30 | – | – | – | – | – | – |
| inline_acl | Are there studies that combine convolutional and recurrent n | 30 | 13 | 13 | 13 | 1 | 1 | 2 |
| inline_acl | Can you direct me to research that explores methods for tran | 30 | 23 | 23 | 2 | 1 | 5 | 1 |
| inline_acl | Can you direct me to studies that explore techniques like qu | 30 | 2 | 2 | 2 | 1 | 1 | 1 |
| inline_acl | Can you list some publications that discuss the evaluation m | 30 | – | – | – | – | – | – |
| inline_acl | Can you point me to a paper that discussed transformer-based | 30 | – | – | – | – | – | – |
| inline_acl | Can you point me to a work that uses diagnostic tools to det | 30 | – | – | – | – | – | – |
| inline_acl | Can you point me to studies discussing methods for evaluatin | 30 | – | – | – | – | – | – |
| inline_acl | Can you point me to studies that explore the impact of diffe | 30 | – | – | – | – | – | – |
| inline_acl | Can you point me towards research on contrastive learning me | 30 | – | – | – | – | – | – |
| inline_acl | Can you point to studies or tasks focused on detecting patro | 30 | 18 | 18 | 25 | 12 | 3 | 13 |
| inline_acl | Can you recommend a conversational QA dataset where the huma | 30 | – | – | – | – | – | – |
| inline_acl | Can you recommend a foundational paper that provides a scala | 30 | – | – | – | – | – | – |
| inline_acl | Can you recommend a paper that uses an NLI model for sentenc | 30 | – | – | – | – | – | – |
| inline_acl | Can you recommend some literature that focuses on dependency | 30 | – | – | – | – | – | – |
| inline_acl | Can you refer me to research that adapts the concept of Word | 30 | – | – | – | – | – | – |
| inline_acl | Can you suggest a corpus that contains French encyclopedia d | 30 | – | – | – | – | – | – |
| inline_acl | Can you suggest any literature that explores the idea of tra | 30 | – | – | – | – | – | – |
| inline_acl | Can you suggest literature on a dataset that categorizes var | 30 | – | – | – | – | – | – |
| inline_acl | Can you suggest literature on enhanced semantic parsing meth | 30 | – | – | – | – | – | – |
| inline_acl | Can you suggest recent studies that have integrated prompt f | 30 | – | – | – | – | – | – |
| inline_acl | Can you suggest some literature that evaluates the ability o | 30 | – | – | – | – | – | – |
| inline_acl | Can you suggest some recent datasets that have been used for | 30 | – | – | – | – | – | – |
| inline_acl | Could you direct me towards a study that explores the potent | 30 | – | – | – | – | – | – |
| inline_acl | Could you point me to research on binary classification syst | 30 | – | – | – | – | – | – |
| inline_acl | Could you point me to studies that discuss the development o | 30 | – | – | – | – | – | – |
| inline_acl | Could you point me to studies that have investigated dialect | 30 | – | – | – | – | – | – |
| inline_acl | Could you point me toward some large-scale multilingual Amaz | 30 | 3 | 3 | 4 | 1 | 1 | 1 |
| inline_acl | Could you provide me with a reference that discusses the dev | 30 | – | – | – | – | – | – |
| inline_acl | Could you recommend datasets that include SQL annotations ov | 30 | – | – | – | – | – | – |
| inline_acl | Could you recommend studies that provide a baseline for expe | 30 | – | – | – | – | – | – |
| inline_acl | Could you suggest a paper that introduces an approach to rel | 30 | – | – | – | – | – | – |
| inline_acl | Could you suggest studies that employ novel methods for capt | 30 | – | – | – | – | – | – |
| inline_acl | Has there been any recent work or competitions focused on th | 30 | – | – | – | – | – | – |
| inline_acl | I am exploring state-of-the-art techniques in language repre | 18 | – | – | – | – | – | – |
| inline_acl | I am looking for research that has explored topic and frame  | 30 | – | – | – | – | – | – |
| inline_acl | I am looking to understand more about sequence-to-sequence p | 30 | 4 | 4 | 2 | 2 | 2 | 2 |
| inline_acl | I would like to understand the theoretical basis for using t | 30 | – | – | – | – | – | – |
| inline_acl | I'm conducting research on computational humor and looking a | 30 | 27 | 27 | 1 | 1 | 5 | 1 |
| inline_acl | I'm exploring efficient transformer architectures for langua | 30 | – | – | – | – | – | – |
| inline_acl | I'm exploring research that utilizes large datasets for the  | 30 | – | – | – | – | – | – |
| inline_acl | I'm exploring ways to enhance question answering systems thr | 30 | 4 | 4 | 2 | 1 | 1 | 1 |
| inline_acl | I'm interested in understanding how perplexity is utilized i | 30 | 12 | 12 | 20 | 14 | 4 | 20 |
| inline_acl | I'm looking for a comprehensive dataset that has been influe | 30 | – | – | – | – | – | – |
| inline_acl | I'm looking for a paper that discusses improvements in const | 30 | – | – | – | – | – | – |
| inline_acl | I'm looking for innovative approaches to data annotation on  | 30 | – | – | – | – | – | – |
| inline_acl | I'm looking into morphological embedding algorithms that bui | 30 | – | – | – | – | – | – |
| inline_acl | I'm looking into the distillation process of language models | 30 | – | – | – | – | – | – |
| inline_acl | I'm researching insertion-based decoding methods for semanti | 30 | 12 | 12 | 3 | 6 | 8 | 4 |
| inline_acl | I'm researching on the efficacy of recurrent networks in lan | 30 | – | – | – | – | – | – |
| inline_acl | I'm searching for studies that explore advancements in depen | 30 | 1 | 1 | 1 | 1 | 1 | 1 |
| inline_acl | In discourse parsing literature, which works have explored p | 30 | – | – | – | – | – | – |
| inline_acl | In researching metrics for human-interaction with computer-a | 30 | – | – | – | – | – | – |
| inline_acl | In the area of argument mining, could you point to literatur | 30 | – | – | – | – | – | – |
| inline_acl | In the context of Named Entity Recognition tasks across mult | 30 | – | – | – | – | – | – |
| inline_acl | In the context of machine translation, can you point me towa | 30 | – | – | – | – | – | – |
| inline_acl | In the context of natural language processing, I am looking  | 30 | – | – | – | – | – | – |
| inline_acl | In the context of simultaneous machine translation, which to | 30 | – | – | – | – | – | – |
| inline_acl | In the field of reinforcement learning models for multi-hop  | 30 | – | – | – | – | – | – |
| inline_acl | What approaches have been used to address the limitations of | 30 | – | – | – | – | – | – |
| inline_acl | What are some approaches to generating sports news reports f | 30 | 9 | 9 | 1 | 1 | 1 | 1 |
| inline_acl | What are some good datasets for conversational question answ | 30 | – | – | – | – | – | – |
| inline_acl | What are some of the key papers to look at for understanding | 30 | – | – | – | – | – | – |
| inline_acl | What are some recent advancements in training systems to par | 30 | – | – | – | – | – | – |
| inline_acl | What are some soft-constrained methods proposed in the liter | 20 | – | – | – | – | – | – |
| inline_acl | What are some studies that leverage statistical machine tran | 30 | – | – | – | – | – | – |
| inline_acl | What are some techniques or tools used in machine learning f | 30 | – | – | – | – | – | – |
| inline_acl | What are the recent developments in evaluating the flow or ' | 30 | – | – | – | – | – | – |
| inline_acl | What paper should I look at if I am interested in the challe | 30 | 22 | 22 | 5 | 2 | 6 | 2 |
| inline_acl | What papers should I refer to if I want to explore datasets  | 30 | – | – | – | – | – | – |
| inline_acl | What prior works suggested that exposure bias could lead to  | 30 | 5 | 5 | 1 | 1 | 1 | 1 |
| inline_acl | What research could I reference to understand the methodolog | 30 | – | – | – | – | – | – |
| inline_acl | What research has been done on annotating user comments with | 30 | – | – | – | – | – | – |
| inline_acl | What research has been done on improving named entity recogn | 30 | 25 | 25 | 1 | 1 | 1 | 1 |
| inline_acl | What research should I explore to understand methods for mat | 30 | – | – | – | – | – | – |
| inline_acl | When using pretrained transformer models for generating sent | 30 | – | – | – | – | – | – |
| inline_acl | Where can I find a corpus of CCG annotations for natural lan | 30 | – | – | – | – | – | – |
| inline_acl | Where can I find a detailed discussion on automating the ass | 30 | 4 | 4 | 3 | 3 | 2 | 3 |
| inline_acl | Where can I find a discourse treebank tailored to Chinese ne | 30 | – | – | – | – | – | – |
| inline_acl | Where can I find a large corpus of annotated social media po | 30 | – | – | – | – | – | – |
| inline_acl | Where can I find a multilingual corpus that includes reviews | 30 | – | – | – | – | – | – |
| inline_acl | Where can I find a paper that discusses annotating events in | 30 | – | – | – | – | – | – |
| inline_acl | Where can I find guidelines on standard practices for probin | 30 | – | – | – | – | – | – |
| inline_acl | Where can I find information on self-attentive parsers that  | 30 | – | – | – | – | – | – |
| inline_acl | Where can I find interdisciplinary research that investigate | 30 | 2 | 2 | 2 | 1 | 2 | 1 |
| inline_acl | Where can I find multilingual datasets used for the task of  | 30 | 4 | 4 | 9 | 6 | 5 | 7 |
| inline_acl | Where can I find research about automatic evaluation metrics | 30 | 4 | 4 | 4 | 1 | 1 | 1 |
| inline_acl | Where might I find a dataset annotated specifically for patr | 30 | 2 | 2 | 1 | 1 | 1 | 1 |
| inline_acl | Where might I find research on the evaluation of consistency | 30 | – | – | – | – | – | – |
| inline_acl | Which corpora are frequently used in research to benchmark E | 30 | – | – | – | – | – | – |
| inline_acl | Which paper specifies the typical configurations used in fin | 30 | 3 | 3 | 4 | 1 | 1 | 1 |
| inline_acl | Which papers should I refer to for learning about the applic | 30 | – | – | – | – | – | – |
| inline_acl | Which studies should I look into that have explored the task | 30 | – | 38 | – | – | – | 7 |
| inline_acl | Which work should I explore to understand the techniques tha | 30 | – | – | – | – | – | – |
| inline_nonacl | *Could you suggest a dataset with legally or ethically conte | 20 | – | – | – | – | – | – |
| inline_nonacl | Are there any papers on training video-language models with  | 30 | – | – | – | – | – | – |
| inline_nonacl | Are there any recent papers investigating the use of expert  | 30 | 1 | 1 | 1 | 1 | 3 | 1 |
| inline_nonacl | Are there any research papers investigating the improvement  | 30 | – | – | – | – | – | – |
| inline_nonacl | Are there any studies investigating example-based approaches | 30 | – | – | – | – | – | – |
| inline_nonacl | Are there any studies investigating sentiment analysis throu | 30 | – | – | – | – | – | – |
| inline_nonacl | Are there any studies on incorporating external commonsense  | 30 | – | – | – | – | – | – |
| inline_nonacl | Are there studies examining how well question answering syst | 30 | – | – | – | – | – | – |
| inline_nonacl | Are there studies that investigate debiasing language models | 30 | – | – | – | – | – | – |
| inline_nonacl | Can you give me a paper that does self-supervised contrastiv | 30 | – | – | – | – | – | – |
| inline_nonacl | Can you recommend a dialogue summarization dataset mined fro | 30 | – | – | – | – | – | – |
| inline_nonacl | Can you recommend research that uses an LLM to generate bett | 20 | – | – | – | – | – | – |
| inline_nonacl | Can you show me a paper that built a large structured knowle | 30 | – | – | – | – | – | – |
| inline_nonacl | Can you suggest research that deals with the multiple input  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you direct me to research that evaluates few-shot slot | 30 | 9 | 9 | 5 | 3 | 4 | 4 |
| inline_nonacl | Could you direct me to studies investigating the enhancement | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you point me to research that tackles the issue of dis | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a contemporary research paper that has a | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a paper that builds a writing assistant  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that does data-augmentation for  | 30 | 28 | 28 | 2 | 1 | 1 | 2 |
| inline_nonacl | Could you recommend a study that examines how cross project  | 30 | 28 | 28 | 2 | 1 | 1 | 1 |
| inline_nonacl | Could you recommend a study that examines how incorporating  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that examines the intricacies of | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that explores a pre-trained mult | 30 | 18 | 18 | 4 | 4 | 4 | 4 |
| inline_nonacl | Could you recommend a study that explores employing variatio | 30 | 2 | 2 | 1 | 1 | 1 | 1 |
| inline_nonacl | Could you recommend a study that explores how language model | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that explores mitigating bias in | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that explores strategies for imp | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that explores the difficulties i | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that explores the improvement of | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that initializes embeddings in m | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates employing grap | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates employing pref | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates enhancing prom | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates enhancing toke | 20 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates graph-based mo | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates guiding abstra | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates how a subset w | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates how contrastiv | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates how integratin | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates incorporating  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates knowledge tran | 30 | 2 | 2 | 1 | 1 | 1 | 1 |
| inline_nonacl | Could you recommend a study that investigates representing e | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates text generatio | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates the implementa | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates the improvemen | 30 | 22 | 22 | 1 | 1 | 1 | 1 |
| inline_nonacl | Could you recommend a study that investigates the use of tra | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that uses feedback-driven decodi | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend articles that explore the role of late i | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research articles that explore the appli | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research papers that explore applying kn | 30 | 2 | 2 | 1 | 1 | 1 | 1 |
| inline_nonacl | Could you recommend research papers that investigate employi | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that analyses prompt tuning as  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that assesses how well language | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that assesses how well large la | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that assesses techniques to mit | 30 | 26 | 26 | 7 | 1 | 1 | 2 |
| inline_nonacl | Could you recommend research that employs a relaxed l0 regul | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that evaluates the performance  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines how an annotator' | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines how decoding stra | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines how multihead att | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines how optimized con | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines how syntactic con | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines the challenges fa | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines the effect of exa | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that explores how the loss of s | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that explores identifying exces | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that has introduced a dual-phas | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that improves knowledge base ge | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that introduces a metric for as | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates applying conv | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates generative mo | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates how to use co | 30 | 10 | 10 | 10 | 2 | 1 | 2 |
| inline_nonacl | Could you recommend research that investigates how to use da | 30 | 2 | 2 | 4 | 1 | 1 | 1 |
| inline_nonacl | Could you recommend research that investigates merging speec | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates methods for f | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates techniques fo | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates the enhanceme | 30 | 7 | 7 | 2 | 1 | 1 | 1 |
| inline_nonacl | Could you recommend research that investigates the impact of | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates the influence | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates using autoenc | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that proposed enhancing the RoB | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend scholarly articles that investigate the  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend studies on hierarchical modeling of user | 30 | 3 | 3 | 8 | 3 | 3 | 3 |
| inline_nonacl | Could you recommend studies that concentrate on analyzing an | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend studies that investigate fine-tuning pre | 30 | 8 | 8 | 7 | 1 | 1 | 1 |
| inline_nonacl | Could you recommend studies that tackle the issue of popular | 30 | 9 | 9 | 1 | 1 | 6 | 1 |
| inline_nonacl | Could you recommend studies which explore how to optimally s | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a dataset containing diverse, intricate na | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a dataset for question-answering framework | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a research article that explores generativ | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study examining how transformer models u | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that evaluates cross-encoder BERT  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that examines how well contrastive | 30 | – | 36 | – | – | – | 10 |
| inline_nonacl | Could you suggest a study that explores a cohesive pre-train | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that explores a compression method | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that explores data annotation para | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that explores employing a beta dis | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that explores improved training me | 30 | 8 | 8 | 2 | 1 | 1 | 1 |
| inline_nonacl | Could you suggest a study that explores the idea of using pr | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that explores the use of multi-mod | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that investigates the incorporatio | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a study that proposes high-parameter effic | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest a thorough comparative analysis or review  | 30 | 4 | 4 | 4 | 2 | 1 | 3 |
| inline_nonacl | Could you suggest a triplet-formatted structured dataset sui | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest an article that leverages the spatial info | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest datasets that can benchmark LLM performanc | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest papers that tackle conversational search b | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research on detecting common errors like a | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that assesses if language models  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that concentrates on pinpointing  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines a system for multim | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines how coreference res | 30 | 1 | 1 | 3 | 1 | 2 | 1 |
| inline_nonacl | Could you suggest research that examines how prompt tuning c | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines how prompt tuning e | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines how strangers excha | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines how the order of in | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines how well language m | 30 | 1 | 1 | 6 | 1 | 2 | 1 |
| inline_nonacl | Could you suggest research that examines how well prompt tun | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines how well structured | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines the application of  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines the challenges face | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that examines the difficulties in | 30 | 8 | 8 | 2 | 1 | 4 | 1 |
| inline_nonacl | Could you suggest research that examines the effects of star | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that explores a pre-trained encod | 30 | 2 | 2 | 1 | 2 | 5 | 4 |
| inline_nonacl | Could you suggest research that explores employing independe | 30 | 28 | 28 | 25 | 22 | 10 | 24 |
| inline_nonacl | Could you suggest research that explores generating syntheti | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that explores the drawbacks of de | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that explores the idea of trainin | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that explores the improvement of  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that includes an online community | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates a clustering-ba | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates across multiple | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates applying combin | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates aspect-based se | 30 | 2 | 2 | 7 | 4 | 1 | 3 |
| inline_nonacl | Could you suggest research that investigates efficient finet | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates employing graph | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates enhancing zero- | 30 | 2 | 2 | 3 | 2 | 1 | 2 |
| inline_nonacl | Could you suggest research that investigates expanding keywo | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates graph-based met | 30 | 1 | 1 | 11 | 5 | 1 | 5 |
| inline_nonacl | Could you suggest research that investigates how cross-atten | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates how hierarchica | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates how many eviden | 30 | 1 | 1 | 2 | 1 | 1 | 1 |
| inline_nonacl | Could you suggest research that investigates how neural lang | 30 | 2 | 2 | 3 | 1 | 1 | 1 |
| inline_nonacl | Could you suggest research that investigates how undetectabl | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates improving retri | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates the use of past | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that investigates training BERT-b | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that offers an in-depth examinati | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that shows multilingual language  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that trains language models speci | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest research that tries to interpret how bi-di | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest some work that develops multimodal models  | 30 | – | – | – | – | – | – |
| inline_nonacl | Could you suggest studies focused on emotion-classification  | 30 | – | – | – | – | – | – |
| inline_nonacl | Has any research explored using other off-the-shelf summariz | 30 | – | – | – | – | – | – |
| inline_nonacl | Has any research tried to mitigate overfitting in weakly-sup | 30 | – | – | – | – | – | – |
| inline_nonacl | Has any study explored the zero-shot extraction of persona c | 30 | 2 | 2 | 1 | 1 | 1 | 1 |
| inline_nonacl | Has there been any research that uses multiple models to lea | 30 | – | – | – | – | – | – |
| inline_nonacl | Has there been any work that improves the work on integrated | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any new metrics been developed to assess the factual al | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any papers tried to address the background-shift proble | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any recent publications explored the use of neural netw | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research efforts been made to gather dialogue data  | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers been published on models for repres | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers collected feedback from real users  | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers critically analyzed the performance | 30 | – | 37 | – | – | – | 5 |
| inline_nonacl | Have any research papers examined the efficacy of multilingu | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers examined whether using language mod | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers explored methods to improve BERT's  | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers introduced a dedicated pre-training | 30 | 2 | 2 | 2 | 1 | 2 | 1 |
| inline_nonacl | Have any research papers investigated human capacity to dist | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers investigated the creation of datase | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers suggested methods for summarizing a | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers suggested techniques for automatica | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any research papers tried to create conversational agen | 30 | – | – | – | – | – | – |
| inline_nonacl | Have any studies explored the creation of memory management  | 30 | – | – | – | – | – | – |
| inline_nonacl | Have there been any advancements in language models that ope | 30 | – | – | – | – | – | – |
| inline_nonacl | How can I locate a dataset containing toxic sentence pairs a | 30 | – | – | – | – | – | – |
| inline_nonacl | How can SQL-to-text be utilized to improve text-to-SQL parsi | 30 | 6 | 6 | 1 | 1 | 3 | 1 |
| inline_nonacl | How can dense retrieval models for open-domain question answ | 30 | 11 | 11 | 10 | 8 | 9 | 11 |
| inline_nonacl | I know about prompt tuning, but have any works tried learnin | 30 | – | – | – | – | – | – |
| inline_nonacl | In multi-hop question answering, is there a paper that explo | 30 | – | – | – | – | – | – |
| inline_nonacl | Is it possible to adatp named entity recognition systems to  | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there a benchmark designed to assess language models' soc | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there a comprehensive dataset available for summarizing b | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there a dataset available for open-domain targeted sentim | 30 | 8 | 8 | 1 | 1 | 1 | 1 |
| inline_nonacl | Is there a dataset containing question-answer pairs used in  | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there a research paper that has developed a customer serv | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there a specialized question answering dataset that conce | 30 | 2 | 2 | 1 | 1 | 1 | 1 |
| inline_nonacl | Is there a study that investigates if large language models  | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there any paper that tried fine-tuning mBERT to enhance w | 30 | 26 | 26 | 3 | 2 | 2 | 2 |
| inline_nonacl | Is there any research that investigates how to use Transform | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there research examining if multilingual pre-trained mode | 30 | 29 | 29 | 5 | 2 | 1 | 2 |
| inline_nonacl | Is there research on a specialized language model designed t | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there research that argues for transparency and open-acce | 30 | – | – | – | – | – | – |
| inline_nonacl | Is there research that investigates embedding multi-bit data | 30 | – | 38 | – | – | – | 4 |
| inline_nonacl | Is there work on text classification that explores using BER | 30 | – | – | – | – | – | – |
| inline_nonacl | What approaches have been suggested to lower the computation | 30 | – | – | – | – | – | – |
| inline_nonacl | What are some scholarly articles that explore scaling laws f | 30 | – | – | – | – | – | – |
| inline_nonacl | What are some scholarly articles that explore the enhancemen | 30 | – | – | – | – | – | – |
| inline_nonacl | What are some studies that explore data-poisoning strategies | 30 | – | – | – | – | – | – |
| inline_nonacl | What are the latest advancements in predicting suicidal tend | 30 | – | – | – | – | – | – |
| inline_nonacl | What are the latest developments in conversational agents th | 30 | – | – | – | – | – | – |
| inline_nonacl | What benchmarks have prior research utilized to assess model | 30 | – | – | – | – | – | – |
| inline_nonacl | What concerns or key points have been highlighted in scholar | 30 | – | – | – | – | – | – |
| inline_nonacl | What difficulties do neural conversational models face, part | 30 | – | – | – | – | – | – |
| inline_nonacl | What literature is available on training semantic parsers wi | 30 | – | – | – | – | – | – |
| inline_nonacl | What methods exist for tailoring news suggestions that consi | 30 | – | – | – | – | – | – |
| inline_nonacl | What papers discuss the effect of false negatives among hard | 30 | – | – | – | – | – | – |
| inline_nonacl | What papers explore replacing schema linking with human anno | 30 | – | – | – | – | – | – |
| inline_nonacl | What recent developments in transformer architecture aim to  | 30 | – | – | – | – | – | – |
| inline_nonacl | What recent research has been conducted on improving few-sho | 30 | – | – | – | – | – | – |
| inline_nonacl | What research articles should I consult to understand a meth | 30 | – | – | – | – | – | – |
| inline_nonacl | What research exists comparing adapter-based tuning and full | 30 | – | – | – | – | – | – |
| inline_nonacl | What research exists on employing generative models with lat | 30 | – | – | – | – | – | – |
| inline_nonacl | What research exists on incorporating knowledge graphs into  | 30 | – | – | – | – | – | – |
| inline_nonacl | What research exists on leveraging syntactic roles and seman | 30 | – | – | – | – | – | – |
| inline_nonacl | What research exists on the impact of scaling on prompt tuni | 30 | – | – | – | – | – | – |
| inline_nonacl | What research exists on using reinforcement learning methods | 30 | – | – | – | – | – | – |
| inline_nonacl | What research has been conducted on applying contrastive tec | 30 | – | – | – | – | – | – |
| inline_nonacl | What research has been conducted on creating neural network  | 30 | – | – | – | – | – | – |
| inline_nonacl | What research has been conducted on determining the ideal se | 30 | – | – | – | – | – | – |
| inline_nonacl | What research has been conducted on enhancing conversational | 30 | – | – | – | – | – | – |
| inline_nonacl | What research has been conducted on incorporating visual dat | 30 | – | – | – | – | – | – |
| inline_nonacl | What research has been conducted on news recommendation engi | 30 | 10 | 10 | 6 | 1 | 1 | 2 |
| inline_nonacl | What research has been conducted on scaling within-document  | 30 | 2 | 2 | 1 | 1 | 1 | 1 |
| inline_nonacl | What research has been conducted on the impact of intervenin | 30 | – | – | – | – | – | – |
| inline_nonacl | What research is available on acquiring sentence embeddings  | 30 | – | – | – | – | – | – |
| inline_nonacl | What research is available on hybrid approaches that combine | 30 | – | – | – | – | – | – |
| inline_nonacl | What research is available on the concept of using prefix to | 30 | – | – | – | – | – | – |
| inline_nonacl | What research should I consult regarding the application of  | 30 | – | – | – | – | – | – |
| inline_nonacl | What resources or toolkits are available to facilitate promp | 30 | – | – | – | – | – | – |
| inline_nonacl | What sources offer research on maintaining factual accuracy  | 30 | 1 | 1 | 2 | 2 | 1 | 2 |
| inline_nonacl | What techniques and frameworks have been suggested for summa | 30 | – | – | – | – | – | – |
| inline_nonacl | What techniques exist for efficiently fine-tuning transforme | 30 | – | – | – | – | – | – |
| inline_nonacl | What techniques exist for incorporating context in detecting | 30 | – | – | – | – | – | – |
| inline_nonacl | What techniques exist to enhance the few-shot fine-tuning pe | 30 | – | – | – | – | – | – |
| inline_nonacl | What techniques have been investigated to enhance multimodal | 30 | – | – | – | – | – | – |
| inline_nonacl | Where can I find a database of good prompts to use for promp | 30 | – | – | – | – | – | – |
| inline_nonacl | Where can I read about the using soft embeddings to elicit k | 30 | – | – | – | – | – | – |
| inline_nonacl | Which method involves training additional prompt tokens for  | 30 | – | – | – | – | – | – |
| inline_nonacl | Which paper has conducted a thorough analysis of how languag | 30 | – | – | – | – | – | – |
| inline_nonacl | Which paper introduced the task of creating extended, cohere | 30 | – | – | – | – | – | – |
| inline_nonacl | Which paper presents a platform that emphasizes evaluating t | 30 | – | – | – | – | – | – |
| inline_nonacl | Which paper shows that generated captions of models are stil | 30 | – | – | – | – | – | – |
| inline_nonacl | Which paper shows that human experts and non-experts focus o | 30 | – | – | – | – | – | – |
| inline_nonacl | Which work introduces sparse attention modules and evaluate  | 30 | – | – | – | – | – | – |
| inline_nonacl | Which work pushes the limit of model quantization in BERT mo | 30 | – | – | – | – | – | – |
| inline_nonacl | Which work shows that only emplying instance-level uncertain | 30 | – | – | – | – | – | – |
| inline_nonacl | Which work shows that reducing the number of training epochs | 30 | – | – | – | – | – | – |
| inline_nonacl | Which work suggests that machine translation models might ge | 30 | – | – | – | – | – | – |
| inline_nonacl | Which works shows that training large language models with p | 30 | – | – | – | – | – | – |
| inline_nonacl | ould you direct me to research that shows that the transfer  | 30 | – | – | – | – | – | – |
| manual_acl | Are there any examples of using dense phrase retrieval syste | 30 | – | 31 | – | – | – | 1 |
| manual_acl | Are there any large-scale and open-source text simplificatio | 30 | – | – | – | – | – | – |
| manual_acl | Are there any papers that build dense retrievers with mixtur | 30 | – | – | – | – | – | – |
| manual_acl | Could you recommend a dataset paper which presents relation  | 30 | – | – | – | – | – | – |
| manual_acl | Find the NLP paper that focuses on dialogue generation and i | 30 | 13 | 13 | 1 | 1 | 2 | 1 |
| manual_acl | Give me a paper proposing to circumvent a single-truth targe | 30 | – | – | – | – | – | – |
| manual_acl | How to achieve zero-shot lip reading? | 30 | – | – | – | – | – | – |
| manual_acl | How to better attract readers to news articles by generating | 30 | – | – | – | – | – | – |
| manual_acl | How to faithfully and explicitly measure the helpfulness of  | 30 | – | 32 | – | – | – | 1 |
| manual_acl | If one would like to train (or evaluate) a helpful assistant | 30 | – | – | – | – | – | – |
| manual_acl | In multimodal (multilingual) abstractive summarization field | 30 | 1 | 1 | 2 | 1 | 1 | 1 |
| manual_acl | Is there a Chinese hate speech paper that constructs an insu | 30 | – | – | – | – | – | – |
| manual_acl | Is there a dataset that allows to perform aspect-based senti | 30 | – | – | – | – | – | – |
| manual_acl | Is there a decoder-only language model that does not use a t | 30 | – | – | – | – | – | – |
| manual_acl | Is there a dialogue dataset where a speaker's utterance is g | 30 | – | – | – | – | – | – |
| manual_acl | Is there a method for measuring the critical errors that a d | 30 | – | – | – | – | – | – |
| manual_acl | Is there a method that measures the information provided in  | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper comparing knowledge distillation and human  | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper exploring the curse of multilinguality for  | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that applies large language models to visua | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that connects the basic elements of storyte | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that links exposure bias to distillation? | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that shows that language models' error dist | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that supports the use of automated coherenc | 30 | – | 38 | – | – | – | 4 |
| manual_acl | Is there a paper that uses Explainable AI techniques to inve | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that uses an app for a popular tabletop gam | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that uses evolutionary algorithms and neura | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that uses similarity scores to check knowle | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that uses the tree structure of math equati | 30 | – | – | – | – | – | – |
| manual_acl | Is there a paper that utilizes the characteristics of human  | 30 | – | – | – | – | – | – |
| manual_acl | Is there a study that shows how to help the demonstration re | 30 | – | – | – | – | – | – |
| manual_acl | Is there a tool that can automatically segment speech and th | 30 | – | – | – | – | – | – |
| manual_acl | Is there an evaluation metric for natural language generatio | 30 | – | – | – | – | – | – |
| manual_acl | Is there any dataset that contains minimally-contrasting soc | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper about style transfer for stories? | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper exploring real speakers and thus performi | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper leverages knowledge distillation of langu | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that address attacks on code models by le | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that aligns speech and text embeddings be | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that applies curriculum learning to vario | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that applies symbolic distillation on bla | 30 | 25 | 25 | 1 | 1 | 1 | 1 |
| manual_acl | Is there any paper that attempts to evaluate the similarity  | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that automatically creates a dataset for  | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that combines causal inference and finetu | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that constructs augmented training data b | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that employs code LLMs to iteratively gen | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that explores and annotates the effective | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that explores using only an encoder-only  | 20 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual_acl | Is there any paper that investigates backdoor attacks across | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that leverages graph neural network by in | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that leverages syntactic rules to explici | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that performs adversarial training on fra | 30 | 16 | 16 | 2 | 1 | 1 | 1 |
| manual_acl | Is there any paper that proposes a new multimodal video data | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that proposes a set of criteria to compre | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that reveals annotation problems in cross | 30 | 21 | 21 | 5 | 4 | 3 | 3 |
| manual_acl | Is there any paper that studies a teacher AI inferring menta | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that tries to investigate LLMs’ capabilit | 30 | 8 | 8 | 2 | 1 | 1 | 1 |
| manual_acl | Is there any paper that uses data collected from the Dark We | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that uses prompt tuning in multi-answer Q | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that uses token-level loss to enhance sen | 30 | – | 37 | – | – | – | 6 |
| manual_acl | Is there any paper that utilizes Gaussian processes to analy | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that utilizes graph structure to model co | 30 | – | – | – | – | – | – |
| manual_acl | Is there any paper that utilizes masked language modeling to | 30 | – | – | – | – | – | – |
| manual_acl | Is there any research paper that can extract attributes from | 30 | – | – | – | – | – | – |
| manual_acl | Is there any work that allows large numbers of model outputs | 30 | – | – | – | – | – | – |
| manual_acl | Is there any work that attacks language models in dialogue g | 30 | – | – | – | – | – | – |
| manual_acl | Is there any works that explores how to achieve balance betw | 30 | – | – | – | – | – | – |
| manual_acl | Is there commonsense reasoning dataset which generates diver | 30 | – | – | – | – | – | – |
| manual_acl | Is there such a factuality evaluation dataset that can be us | 30 | – | – | – | – | – | – |
| manual_acl | Is there such a reading comprehension dataset in understandi | 30 | – | – | – | – | – | – |
| manual_acl | Provide an example of a paper which proposes a method to lea | 30 | – | – | – | – | – | – |
| manual_acl | What are some data-efficient ways to learn text embeddings t | 30 | – | – | – | – | – | – |
| manual_acl | What are some methods for solving the class-incremetal conti | 30 | – | – | – | – | – | – |
| manual_acl | What is a large event-coverage general-domain event argument | 30 | – | – | – | – | – | – |
| manual_acl | What is the first paper to address the problem of predicting | 30 | – | – | – | – | – | – |
| manual_acl | What is the performance of large language models in text sum | 30 | – | – | – | – | – | – |
| manual_acl | What limitations do large language models have in evaluating | 30 | – | – | – | – | – | – |
| manual_acl | What paper compares humans' and language models' non-literal | 30 | – | 39 | – | – | – | 1 |
| manual_acl | What work attempts to explore multi-hop reasoning by densify | 30 | – | – | – | – | – | – |
| manual_acl | Which article first proposed shuffled-group-whitening to sol | 30 | 13 | 13 | 1 | 1 | 1 | 1 |
| manual_acl | Which dataset supports narration generation and temporal loc | 30 | – | – | – | – | – | – |
| manual_acl | Which family of model generally perform the best for the eve | 30 | – | – | – | – | – | – |
| manual_acl | Which is the first multimodal model combining text and speec | 30 | – | – | – | – | – | – |
| manual_acl | Which knowledge graph completion method focuses on reducing  | 30 | – | – | – | – | – | – |
| manual_acl | Which language model distillation paper that first identifie | 30 | 5 | 5 | 1 | 1 | 2 | 1 |
| manual_acl | Which numerical reasoning paper first published a dataset th | 30 | – | – | – | – | – | – |
| manual_acl | Which paper about parameter-efficient finetuning first propo | 30 | – | – | – | – | – | – |
| manual_acl | Which paper combines the advantages of different frameworks  | 30 | – | – | – | – | – | – |
| manual_acl | Which paper did a comprehensive survey of the code large lan | 21 | – | – | – | – | – | – |
| manual_acl | Which paper employs a two-stage approach in generative model | 30 | – | – | – | – | – | – |
| manual_acl | Which paper enables interactive semantic parsing by training | 30 | – | – | – | – | – | – |
| manual_acl | Which paper explored training a GPT-2 for automatic diagnosi | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first aggregates statements to represent politic | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first applied the chain-of-thought technique in  | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first apply mixture of experts idea to large lan | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first attempts to take potential dependencies am | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first combines different methods for uncertainty | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first combines rewriting and expansion methods t | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first conducted the positioned error test for th | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first construct large-scale corpus to improve in | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first constructed a structured knowledge base to | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first explored In-context learning in a cross li | 30 | 4 | 4 | 5 | 1 | 1 | 1 |
| manual_acl | Which paper first found that multilingual models can inferen | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first introduced document content as an intermed | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first propose to mask positions to pre-train mul | 30 | 17 | 17 | 1 | 1 | 1 | 1 |
| manual_acl | Which paper first proposed a cross-domain language model to  | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first proposed extracting the pair of target and | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first proposed shared adapter module across laye | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first proposed to combine pretrained masked lang | 30 | 3 | 3 | 1 | 1 | 1 | 1 |
| manual_acl | Which paper first proposed to only update some original weig | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first published a real-world Chinese-English tex | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first shows that it is possible to maintain high | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first shows that large language models can be pr | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first studied the efficiency robustness of multi | 30 | – | – | – | – | – | – |
| manual_acl | Which paper first use the attention weights to guide the sim | 30 | 2 | 2 | 2 | 1 | 1 | 1 |
| manual_acl | Which paper first used structural information for coherence  | 30 | – | – | – | – | – | – |
| manual_acl | Which paper found that mutual learning benefits multlingual  | 30 | – | – | – | – | – | – |
| manual_acl | Which paper highlights the need for leveraging all available | 30 | – | – | – | – | – | – |
| manual_acl | Which paper introduce a DRO (distribution robust optimizatio | 30 | – | – | – | – | – | – |
| manual_acl | Which paper introduced the human-evaluated timeliness metric | 30 | – | 35 | – | – | – | 1 |
| manual_acl | Which paper introduces the R-GCN technique into document-lev | 30 | – | 36 | – | – | – | 14 |
| manual_acl | Which paper investigates the influence of the diversity of s | 30 | – | – | – | – | – | – |
| manual_acl | Which paper is among the earliest to train on extensive coll | 30 | – | – | – | – | – | – |
| manual_acl | Which paper is the first to comprehensively review the progr | 30 | – | – | – | – | – | – |
| manual_acl | Which paper makes sure that the questions used in the paper  | 30 | – | – | – | – | – | – |
| manual_acl | Which paper measured how well the source-translation contrib | 30 | – | – | – | – | – | – |
| manual_acl | Which paper presents an easy to implement and high performin | 30 | – | – | – | – | – | – |
| manual_acl | Which paper produces a dataset for text simplification in ov | 30 | – | – | – | – | – | – |
| manual_acl | Which paper proposed a learning-based data augmentation meth | 30 | – | – | – | – | – | – |
| manual_acl | Which paper proposed decomposing the logit update of each of | 30 | – | – | – | – | – | – |
| manual_acl | Which paper proposed dictionary-based Bayesian inference to  | 30 | – | – | – | – | – | – |
| manual_acl | Which paper proposed the integration of human translators' c | 30 | – | – | – | – | – | – |
| manual_acl | Which paper proposes a memory-efficient optimizer considerin | 30 | – | 32 | – | – | – | 1 |
| manual_acl | Which paper proposes the two-stage training method, i.e., ta | 30 | – | – | – | – | – | – |
| manual_acl | Which paper proposes to use rewriting based approaches to de | 30 | – | – | – | – | – | – |
| manual_acl | Which paper showed that social relationships were helpful fo | 30 | – | – | – | – | – | – |
| manual_acl | Which paper shows assessment of training instabilities at di | 30 | – | – | – | – | – | – |
| manual_acl | Which paper shows that in instruction tuning, the instructio | 30 | – | – | – | – | – | – |
| manual_acl | Which paper studies how current retrieval systems handle que | 30 | – | – | – | – | – | – |
| manual_acl | Which paper studies the concept of enhancing the coverage of | 30 | – | – | – | – | – | – |
| manual_acl | Which paper surveyed the datasets and tasks of asking clarif | 30 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual_acl | Which paper used both automatically generated and manual tem | 30 | 19 | 19 | 4 | 1 | 2 | 2 |
| manual_acl | Which paper utilizes language models to generate singable ly | 30 | – | – | – | – | – | – |
| manual_acl | Which paper was the first to propose combining human spoken  | 30 | – | – | – | – | – | – |
| manual_acl | Which papers develop methods to make in-context learning mor | 30 | – | – | – | – | – | – |
| manual_acl | Which papers were among the first to explore the task of tar | 30 | 13 | 13 | 1 | 1 | 1 | 1 |
| manual_acl | Which pre-trained model is specifically designed for low-res | 30 | 2 | 2 | 4 | 1 | 1 | 1 |
| manual_acl | Which research paper leverages event structure information f | 30 | – | – | – | – | – | – |
| manual_acl | Which vision-language model can demonstrate that visual grou | 30 | – | – | – | – | – | – |
| manual_acl | Which vision-language model paper in 2023 developed techniqu | 30 | 17 | 17 | 1 | 1 | 1 | 1 |
| manual_acl | Which was the first paper to explore the online adaptation o | 30 | – | – | – | – | – | – |
| manual_acl | Which work discusses an analysis of source and target contri | 30 | – | – | – | – | – | – |
| manual_acl | Which work proposes an approach to improve candidate respons | 30 | – | – | – | – | – | – |
| manual_acl | what's the first paper that manages to handle KBQA using LLM | 30 | – | – | – | – | – | – |
| manual_acl | which paper first focuses on addressing the over-smoothing i | 30 | 7 | 7 | 1 | 1 | 2 | 1 |
| manual_iclr | Are there any papers that construct convolutional networks w | 30 | – | – | – | – | – | – |
| manual_iclr | Are there any papers that study whether you can identify if  | 19 | – | – | – | – | – | – |
| manual_iclr | Are there any papers that use a world model for planning to  | 30 | – | – | – | – | – | – |
| manual_iclr | Are there datasets and benchmarks available for measuring LL | 30 | – | – | – | – | – | – |
| manual_iclr | Are there sequential learning guarantees for configuring a l | 30 | – | – | – | – | – | – |
| manual_iclr | Can we find the solution of the Bilevel optimization when th | 30 | 8 | 8 | 7 | 5 | 7 | 7 |
| manual_iclr | Can we learn to represent an image with arbitary numbers of  | 30 | – | – | – | – | – | – |
| manual_iclr | Can we reduce visual tokens in vision transformers right fro | 30 | – | – | – | – | – | – |
| manual_iclr | Can you find a dataset that shows LLM-based evaluation may n | 30 | – | – | – | – | – | – |
| manual_iclr | Can you find a research paper that discusses using structure | 30 | – | – | – | – | – | – |
| manual_iclr | I'm using Local SGD with a decaying learning rate for distri | 30 | – | – | – | – | – | – |
| manual_iclr | In video diffusion models, is there any paper that tried dec | 30 | – | – | – | – | – | – |
| manual_iclr | Is there a paper illustrating that pre-trained transformers  | 30 | – | – | – | – | – | – |
| manual_iclr | Is there a paper that takes a mixed machine learning and sol | 30 | – | – | – | – | – | – |
| manual_iclr | Is there a paper which applies Bayesian optimization to modu | 30 | – | – | – | – | – | – |
| manual_iclr | Is there a paper which proposes a general data selection met | 30 | – | – | – | – | – | – |
| manual_iclr | Is there a parameter-efficient fine-tuning method (PEFT) tha | 30 | – | – | – | – | – | – |
| manual_iclr | Is there a single GNN model that can inductively generalize  | 19 | – | – | – | – | – | – |
| manual_iclr | Is there a theory paper that explains why sometimes tuning m | 30 | – | – | – | – | – | – |
| manual_iclr | Is there an existing dataset of images with alt-text that al | 30 | 1 | 1 | 2 | 1 | 2 | 1 |
| manual_iclr | Is there any generalizable NeRF paper that disentangles text | 30 | – | – | – | – | – | – |
| manual_iclr | Is there any paper applies off-shelf GPT-2 model in D4RL tas | 30 | – | – | – | – | – | – |
| manual_iclr | Is there any paper improves adversarial training by forming  | 30 | – | – | – | – | – | – |
| manual_iclr | Is there any paper that explores ways to parameterize neural | 30 | – | – | – | – | – | – |
| manual_iclr | Is there any paper that previously proposed to control a ris | 30 | – | – | – | – | – | – |
| manual_iclr | Is there any paper that seamlessly integrates the multigrid  | 18 | – | – | – | – | – | – |
| manual_iclr | Is there any paper that theoretically explains why in-contex | 30 | – | – | – | – | – | – |
| manual_iclr | Is there any paper that uses Lipschitz continuity in learnin | 30 | – | – | – | – | – | – |
| manual_iclr | Is there any paper trying to improve MLE for auto-regressive | 30 | 11 | 11 | 1 | 1 | 3 | 1 |
| manual_iclr | Name a paper which proposes a probabilsitic formulation of r | 30 | – | – | – | – | – | – |
| manual_iclr | What are some evaluation benchmarks for LLM privacy at infer | 30 | – | – | – | – | – | – |
| manual_iclr | What are the key advantages of coupling neural SDEs with neu | 30 | – | – | – | – | – | – |
| manual_iclr | What is a paper studying data being collected in bundles in  | 20 | – | – | – | – | – | – |
| manual_iclr | What is the first paper that theoretically studies training  | 30 | – | – | – | – | – | – |
| manual_iclr | What is the first paper that uses the generalized linear mod | 30 | – | – | – | – | – | – |
| manual_iclr | What molecular representation learning paper introduced a be | 30 | – | – | – | – | – | – |
| manual_iclr | What open-source dataset combined knowledge retrieval with c | 30 | 9 | 9 | 1 | 1 | 1 | 1 |
| manual_iclr | What paper considers sensitive data issue when prompting lar | 30 | – | – | – | – | – | – |
| manual_iclr | What paper evaluated the ability of visual few-shot learning | 30 | – | – | – | – | – | – |
| manual_iclr | What paper first adapted ControlNet to generate continuous v | 30 | – | – | – | – | – | – |
| manual_iclr | What paper first associate the modeling frequency with input | 30 | – | – | – | – | – | – |
| manual_iclr | What paper first extends rotary positional encoding (RoPE) f | 30 | – | – | – | – | – | – |
| manual_iclr | What paper first proposed a robust perceptual similarity met | 30 | – | – | – | – | – | – |
| manual_iclr | What paper first proposes that simply reversing the output c | 30 | – | – | – | – | – | – |
| manual_iclr | What paper first showed that you can score the code explanat | 30 | – | – | – | – | – | – |
| manual_iclr | What paper first used the technique of prompt engineering to | 30 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual_iclr | What paper first uses decoupled workers in distributed RL sy | 30 | – | – | – | – | – | – |
| manual_iclr | What paper investigated the effect of the relative position  | 30 | – | – | – | – | – | – |
| manual_iclr | What paper is the first to prove finetuned LLM can be a reli | 30 | – | – | – | – | – | – |
| manual_iclr | What paper mitigates language model sampling errors due to t | 30 | – | – | – | – | – | – |
| manual_iclr | What paper mitigates the vocabulary size limitation when pre | 30 | – | – | – | – | – | – |
| manual_iclr | What paper proposes breaking down programming problems by pr | 30 | – | – | – | – | – | – |
| manual_iclr | What paper provides generalization bounds for self supervise | 30 | – | – | – | – | – | – |
| manual_iclr | What paper showed first that one can build a fully different | 30 | – | – | – | – | – | – |
| manual_iclr | What paper shows that RLAIF can fully replace RLHF to align  | 30 | – | – | – | – | – | – |
| manual_iclr | What research first proposed a new kind of cascaded diffusio | 30 | – | – | – | – | – | – |
| manual_iclr | What work first uses LLM to code robotic simulation tasks an | 30 | 25 | 25 | 9 | 2 | 1 | 3 |
| manual_iclr | What work proposes a model to learn a latent regular cell co | 30 | – | – | – | – | – | – |
| manual_iclr | What work proposes to combine video foundation models with v | 30 | – | – | – | – | – | – |
| manual_iclr | Which backdoor paper first used the CLIP to suppress benign  | 30 | – | – | – | – | – | – |
| manual_iclr | Which foundation model paper first proposed a time series mo | 30 | – | – | – | – | – | – |
| manual_iclr | Which is one of the first papers to highlight and resolve th | 30 | – | – | – | – | – | – |
| manual_iclr | Which machine learning paper proposed certified robustness i | 30 | – | – | – | – | – | – |
| manual_iclr | Which multimodal large language model represents visual data | 30 | – | – | – | – | – | – |
| manual_iclr | Which neural theorem proving paper first attempted to prove  | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper considers both weights and activations when prun | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper contains quantitative results demonstrating taki | 30 | – | 35 | – | – | – | 1 |
| manual_iclr | Which paper examined the scalability of instruction-tuning w | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first applied the chain of thought concepts in 3 | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first derived online occupany estimation techniq | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first found that REINFORCE works better than act | 20 | – | – | – | – | – | – |
| manual_iclr | Which paper first found that when transformers are trained t | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first investigates the knowledge preferences of  | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first proposes a unified framework for black-box | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first proved that wide-enough transformer archit | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first showed that task-specific knowledge embedd | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first studied differential privacy for in-contex | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first study POMDP with enhanced feedback on obse | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first tried to fine-tune LLMs with chain-of-thou | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper first used language models to emulate tool execu | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper formally defines the problem of model selection  | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper found that using common character encodings and  | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper in human motion generation can control the spati | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper is the first to model the helpfulness and harmle | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper proposes an alignment framework that steers lang | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper proposes to integrate black-box LLMs with a pool | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper studies how difficult is a policy learning probl | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper systematically examed the input mismatch between | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper trains on linear regression to hypothesize how f | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper uses the latent diffusion model for the first ti | 30 | – | – | – | – | – | – |
| manual_iclr | Which paper utilized MMD flows with Riesz kernels to solve B | 30 | 25 | 25 | 3 | 3 | 3 | 3 |