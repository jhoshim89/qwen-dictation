# Promotion Automation Scope

## Allowed in the MVP

- Generate draft posts from `promo/posts.yaml`.
- Adapt one draft for X, Threads, Show HN, or Reddit.
- Create UTM-style links when a landing page exists.
- Save posting history in `promo/metrics.md`.
- Fetch GitHub star count manually or with `gh repo view`.
- Draft reply candidates from `promo/reply-bank.md`.

## Manual approval required

- Publishing a post.
- Replying to another person.
- Posting in a subreddit or community.
- Editing the README in response to public feedback.

## Not allowed

- Automatic replies to keyword searches.
- Automatic DMs.
- Automatic likes, follows, reposts, or stars.
- Multiple accounts posting the same message.
- Asking people to star in exchange for anything.

## Minimal command workflow

Until a script is needed, use the files directly:

```bash
rg -n "id:|platform:|title:|text:" promo/posts.yaml
gh repo view jhoshim89/qwen-dictation --json stargazerCount,description,repositoryTopics
```

Add a script only after the manual workflow becomes repetitive.
