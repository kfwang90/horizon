# Contributing to Horizon

Thanks for your interest in contributing to Horizon.

## Ways to Contribute

You can contribute in more than one way:

- Report bugs or suggest features by opening an issue
- Improve code, documentation, or examples through pull requests
- Contribute reusable processing profiles for new content domains
- Share valuable news sources with the community through the website

## Code Contributions

If you want to contribute code or docs:

1. Fork the repository
2. Create a new branch
3. Make your changes
4. Open a pull request with a clear description

Please keep pull requests focused and easy to review.

## Contribute a Processing Profile

A processing profile is a reusable editorial policy for one content domain. It
defines what content belongs to the domain, how Horizon scores it, and which
content blocks Horizon generates. Profiles are prompt and JSON files, so adding
one does not require changing Python code.

Add a new directory under `profiles/<id>/` containing:

- `profile.json` for the profile contract and output blocks
- `match.md` for content routing rules
- `analysis.md` for the scoring rubric
- `enrichment.md` for output instructions

Built-in profiles participate in automatic routing. Contributions should
therefore describe a clear content domain, be useful beyond one person's source
list, and avoid overlapping an existing profile without a meaningful difference
in evaluation or output. Keep personal thresholds and topic-deduplication
preferences in runtime configuration rather than the profile.

See [Processing Profiles](docs/profiles.md#contributing-a-profile) for the full
format and submission checklist.

## Share Sources

Horizon also welcomes **source contributions**, not just code.

If you discover high-quality sources worth sharing with other users, please submit them via **[horizon1123.top](https://horizon1123.top)**.

Good examples include:

- niche RSS or Atom feeds
- valuable Hacker News or Reddit sources
- notable GitHub repositories or release sources
- high-signal Telegram channels
- other reliable tech news sources

## Before You Submit

Please make sure your contribution is:

- relevant to Horizon users
- clear and well-described
- respectful of copyright and platform rules

## Questions

If you are unsure whether something fits, feel free to open an issue first.
