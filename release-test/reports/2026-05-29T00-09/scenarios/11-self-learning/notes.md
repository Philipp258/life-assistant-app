# 11 — Self-learning from feedback

**Status:** green

## Tried

- Asked for a quick casual free-evening idea.
- Gave natural negative feedback without mentioning memory, self-improvement, labels, or tasks.
- Approved the proposed behavior-memory update.
- Opened the captured improvement task.
- Checked Core memory.
- Started a fresh chat and asked for another quick idea.

## Worked

- After the prompt fix, Ada created an `improve-life-assistant` task from the feedback.
- The task description captured concrete evidence: what was asked, what Ada did, and what the user corrected.
- Main chat proposed exact behavior-memory wording and waited for approval.
- After approval, Core memory updated.
- A fresh chat used the learned behavior, asking whether the user wanted something active or restful before giving a plan.

## Friction

- The first attempt before the prompt fix proposed/saved memory but did not create an improvement item. Fixed in commit `c5a5e79` and retested green.

## Rating

Green. The full capture, approval, apply, and verification path worked after the fix.
