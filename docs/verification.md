# Verification Record

This record distinguishes deterministic application checks, authored demonstrations and actual model behavior. Passing application tests does not establish review accuracy.

## Offline Application Checks — October 25, 2026

The current candidate passes **185 offline tests** on Python 3.10.1. The suite covers immutable Git snapshots, restricted context tools, sensitive-content admission, SDK protocol and transport handling, request sizing, budgets, deadlines, evidence validation, workflow boundaries, result reuse and publication races.

The [offline showcase](showcase.md) uses authored responses through the official SDK's mocked HTTP transport. It demonstrates a Python contract regression, a nonempty clean Python refactor and a JavaScript contract regression, with verified source references and cache-only reuse. These examples make no external provider requests and do not measure model accuracy.

## Real Local Model Samples — October 19, 2026

Three local analyses used `claude-haiku-5-5` over the immutable showcase snapshots below. The runtime included the sensitive-field, workflow-test, large-hunk and final-request-sizing fixes now present in this candidate. These were actual provider requests, separate from the authored showcase responses.

| Sample | Observed result | Local quality verdict |
| --- | --- | --- |
| Python defect, head `8367e88dd02514f04abf6a8f7cff866d7b0b213f` | Detected the broken Python `total` contract, but also reported a false high-severity finding against an independent JavaScript caller. The Python finding had no inline anchor. | Failed the sample's quality criteria. |
| Clean Python refactor, head `6de002ec39871b44b28be18832c9292c16daecd7` | Reported no findings for a nonempty change preserving the contract. | Passed this local sample. |
| JavaScript defect, head `b32bce5c125307768013d0dca06cec52ae54af1e` | Detected the missing `total` property, cited the unchanged caller and anchored the finding to the changed producer. | Passed this local sample. |

All three used base `944ebe18a4f9e8f6255e863e328f2379777366a0` and reported **partial coverage**. A passing sample or severity check does not certify a complete review. Three development examples are not an accuracy benchmark. Valid source hashes establish which text was cited; they do not prove that the model's interpretation or dependency claim is correct.

The [example PRs](showcase.md#github-examples) show authored harness demonstrations, not these local model responses. Their synthetic outcomes must not be substituted for the mixed local results above.

## Hosted Integration Status

The paid **Claude PR review** workflow is disabled. Hosted provider execution, credential isolation, publication and cache-only integration have not been accepted for the current candidate; enforced merge controls remain unverified. Earlier historical runs exercised older revisions and do not establish those properties for this candidate.

Public source and offline demonstrations can be inspected without enabling paid review. Before choosing hosted deployment, complete the [credential and workflow setup](runtime-configuration.md#credential-and-workflow-trust), verify the repository's actual permissions and merge rules, and perform a separately bounded live integration check. Human judgment remains necessary for every finding.
