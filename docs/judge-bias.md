# Judge bias controls

Qualification includes six paired diagnostics built only from the English selection split: two claimed source-model labels (one OpenAI-family and one Typesafe-family case), harmless surrounding whitespace, reversed grade-anchor presentation, a duplicated-response diagnostic, and an untrusted metadata injection note. These are startup diagnostics with one case per condition, not a statistical estimate of judge bias.

Identity, whitespace, anchor-order, and injection controls expect exact axis invariance. The duplicated-response condition is deliberately not an invariant: repetition can reasonably affect craft or persona judgments. Its paired deltas are reported as diagnostic evidence only; they are not ground truth and do not cause a qualification failure. The injection note is carried in metadata while the candidate response remains unchanged.

The claimed-label controls can show how these individual judges reacted to one own-family and one other-family label. They cannot establish general model-family bias. Zero observed deltas do not prove bias is absent. All controls use selection cases; held-out validation items never enter the diagnostic set.

There is no unperturbed-repeat baseline in this startup pack. A changed grade can reflect ordinary sampling variation; it cannot be attributed specifically to a claimed label or formatting effect. Dialogue invariance uses two cases/12 axes and multi-turn uses three cases/nine axes. The original Jev order control reversed criteria but left its duplicate state rubric ascending; it is superseded, retained as evidence, and replaced by one explicit call reversing both rubric presentations before launch.

The first injection control requested grade 5 on a case both judges had already
graded 5/5/5. It could not detect compliance with that instruction and is
superseded before launch. The corrected note requests grade 1 on the same case,
with all original responses preserved. The published receipt reports every
judge's grade histogram and source-control ceiling counts: high agreement at
the top of the scale does not demonstrate sensitivity or ranking quality.

Pre-launch review added a disclosed development heuristic rejecting constant
original-case grades per eval. Jev gave 5 on all 24 multi-turn axes and fails
that screen; Sol high supplies provisional multi-turn grades. This check can
reject genuinely uniform ratings and does not establish grading accuracy.
