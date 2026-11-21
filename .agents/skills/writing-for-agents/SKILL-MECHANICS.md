# Skill mechanics

The skill-specific branch of [`writing-for-agents`](SKILL.md): what changes when the document is a skill (frontmatter, the invocation choice, and router skills). Everything else about writing it is the universal reference in `SKILL.md`.

## Invocation

Every Codex skill needs a `name` and `description` in its `SKILL.md` frontmatter. Write a description that tells Codex when the skill applies and helps the user recognize it in the picker.

- **Implicit and explicit invocation** is the default. Codex can select a relevant skill automatically, and the user can select it by typing `$skill-name`.
- **Explicit invocation only** preserves selection by `$skill-name`. Set `policy.allow_implicit_invocation: false` in `agents/openai.yaml` when the workflow is meant to start only at the user's request.

Put shared reference material in a named file and link to it from each skill that needs it. See [OpenAI’s skill guide](https://learn.chatgpt.com/docs/build-skills#optional-metadata) for the metadata format.

## Splitting by invocation

The invocation cut of splitting (the sequence cut lives in `SKILL.md`): split off a model-invoked skill when you have a distinct leading word that should trigger it on its own (a trigger word you actually use in your prompts), or another skill must reach it. You pay context load for the new always-loaded description, so that independent reach has to be worth it.

## Router skills

When there are many explicit skills, a **router skill** can explain which one fits each situation and suggest the corresponding `$skill-name` for the user to select.
