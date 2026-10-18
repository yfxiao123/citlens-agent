# bench: screen triage vs. search order (LitSearch, frozen questions)

- questions: 15 (the engine's frozen-planner set — the published recall@20=33.3% sample)
- sources: arxiv, semantic_scholar, openalex, crossref × depth 20 · families: agent(planned, frozen) + raw
- semantic model: BAAI/bge-base-en-v1.5
- arms share the SAME recall pool; only the ordering differs

| arm | gold in pool % | R@5 | R@10 | R@20 | MRR@100 |
|---|---|---|---|---|---|
| firstwins | 13.3 | 0.067 | 0.067 | 0.067 | 0.02 |
| rrf_global | 33.3 | 0.0 | 0.067 | 0.067 | 0.013 |
| screen_lex | 13.3 | 0.067 | 0.067 | 0.067 | 0.035 |
| screen_full | 13.3 | 0.067 | 0.133 | 0.133 | 0.075 |
| sem_only | 13.3 | 0.133 | 0.133 | 0.133 | 0.056 |
| screen_union | 33.3 | 0.267 | 0.267 | 0.333 | 0.178 |

## per question (gold first-rank; – = not in pool)

| set | question (60c) | pool | firstwins | rrf | lex | full | sem | union |
|---|---|---|---|---|---|---|---|---|
| inline_acl | Can you point to studies or tasks focused on detecting patro | 48 | 4 | 9 | 33 | 8 | 2 | 12 |
| inline_acl | Where can I find a detailed discussion on automating the ass | 60 | 22 | 23 | 2 | 1 | 3 | 1 |
| inline_nonacl | Are there any studies on incorporating external commonsense  | 47 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend a study that investigates graph-based mo | 60 | – | 69 | – | – | – | 4 |
| inline_nonacl | Could you recommend research that evaluates the performance  | 59 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that examines how syntactic con | 57 | – | – | – | – | – | – |
| inline_nonacl | Could you recommend research that investigates applying conv | 51 | – | – | – | – | – | – |
| inline_nonacl | Is there a study that investigates if large language models  | 48 | – | 81 | – | – | – | 3 |
| manual_acl | Is there a paper that shows that language models' error dist | 59 | – | – | – | – | – | – |
| manual_acl | Is there a paper that uses evolutionary algorithms and neura | 60 | – | 52 | – | – | – | 1 |
| manual_acl | Which paper studies the concept of enhancing the coverage of | 30 | – | – | – | – | – | – |
| manual_acl | Which work discusses an analysis of source and target contri | 19 | – | – | – | – | – | – |
| manual_iclr | Are there any papers that study whether you can identify if  | 47 | – | – | – | – | – | – |
| manual_iclr | Are there any papers that use a world model for planning to  | 30 | – | – | – | – | – | – |
| manual_iclr | What research first proposed a new kind of cascaded diffusio | 47 | – | – | – | – | – | – |