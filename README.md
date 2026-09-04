# deadowners

Finds the lines in your CODEOWNERS that do nothing — patterns that match no
file in the repository, and rules a later line has quietly taken every file
from. It is for anyone who has a CODEOWNERS long enough that nobody reads it
top to bottom any more.

CODEOWNERS fails silently. A rule pointing at a directory that was renamed
two years ago looks exactly like a rule that works. A rule shadowed by a
later one looks exactly like a rule that works. Nothing goes red; the review
request simply never fires, and the team named on the line never finds out
they stopped being asked.

```
$ deadowners
.github/CODEOWNERS

  line 11:  packages/widgets/       @acme/widgets
      matches no file in the repository
      Nothing here matches it, so it has never requested a review from
      anyone. Usually the path moved and the rule didn't; sometimes the
      rule is `dir/*` where `dir/` was meant, which stops at the first
      level and misses everything nested underneath.

  line 14:  *.tf                    @acme/infra
      matches 1 file, but owns none
      taken by:
        line 15:  infra/                  @acme/platform   (1 file)
          infra/main.tf
      CODEOWNERS is last-match-wins, so a later line has taken every file
      this one covers. The owners named here are never asked for a review
      of anything. Moving the rule below the ones listed would give it
      back its files -- if that is what you meant.

7 rules checked against 10 files, 2 findings
```

## Install

```
pip install git+https://github.com/committed-nightly/deadowners
```

Python 3.10+, no dependencies, and it needs `git` on PATH.

## Usage

Run it in a repository. It finds CODEOWNERS the way GitHub does — `.github/`,
then the root, then `docs/` — and checks it against every file git is
tracking.

```
deadowners                       # check this repository
deadowners --ref v2.1.0          # check the tree at a revision
deadowners --file docs/CODEOWNERS
deadowners --json                # for something other than a human
deadowners --explain src/api/main.py
```

`--explain` is the one to reach for when a finding surprises you. It shows
every rule that matches a path and which one wins:

```
$ deadowners --explain docs/index.md
docs/index.md

  line 2:  *                       @acme/eng
      matches, but is overruled below
  line 5:  docs/                   @acme/writers
      wins.  owner: @acme/writers
```

### Exit codes

| code | meaning |
| ---- | ------- |
| 0 | every rule owns at least one file |
| 1 | at least one rule does nothing |
| 2 | the check could not run |

2 is deliberately not 1 and very deliberately not 0. No repository, no
CODEOWNERS, a `--ref` that doesn't resolve — all of those mean nobody looked,
and "nobody looked" reported as a green tick is worse than no check at all.

A CODEOWNERS that exists and contains no rules is a **pass**: there is
nothing in it that can be dead. A CODEOWNERS that is *missing* is a 2 — you
have pointed a CODEOWNERS checker at a repository that has none, and the
likeliest reason is that you are running it somewhere unexpected.

### In CI

```yaml
- run: pip install git+https://github.com/committed-nightly/deadowners
- run: deadowners
```

## What it reports

| kind | what it means |
| ---- | ------------- |
| `unmatched` | the pattern matches no file that exists |
| `shadowed` | it matches files, but later rules own every one of them |
| `pointless-unowning` | a rule with no owners, removing an owner nothing had |
| `bad-pattern` | syntax CODEOWNERS doesn't have, so GitHub skips the line |
| `ignored-file` | a whole CODEOWNERS that GitHub never opens |

The last two are worth a word each.

**`bad-pattern`.** CODEOWNERS is *not* gitignore. `!` negation, `[a-z]`
character ranges and `\` escaping all work in `.gitignore` and none of them
work here. GitHub doesn't reject the file over it — the line is skipped, and
everything it was meant to own falls through to whatever else matches.

**`ignored-file`.** GitHub stops at the first CODEOWNERS it finds. If you
have `.github/CODEOWNERS` and a root `CODEOWNERS`, the second one is not
merged, not warned about, and every rule in it is dead however good it is.

## How it decides

Take every file git is tracking, run the whole rule list over each one, and
see which rule wins. A rule that wins nothing is dead.

That is deliberately dumber than the alternative, which is to prove by
pattern algebra that one rule subsumes another. It is dumber because the
interesting dead rules in real repositories aren't subsumed by any single
later rule — they get eaten by three later rules between them, which a
pairwise check cannot see. The cost is that a finding is a statement about
*this* repository at *this* revision: a rule matching nothing today may be
waiting for a file somebody adds tomorrow.

So every finding carries its evidence — the files, and the exact later rule
that took each one. You should be able to check a claim by eye in about five
seconds, and you should, because the point of the tool is to get you to
delete a line, and deleting the wrong line is worse than leaving it.

60,000 files against 300 rules takes about 2 seconds.

### The pattern matching, and the bit that is guesswork

CODEOWNERS patterns are nearly gitignore patterns. The difference catches
every implementation out, including two that have open bugs about it.

gitignore matches *directories*, and everything under a matched directory is
matched too. So to git, `docs/*` matches the directory `docs/build-app/` and
therefore matches `docs/build-app/troubleshooting.md`. GitHub's docs say the
opposite in as many words: `docs/*` matches `docs/getting-started.md` "but
not further nested files". You cannot use `git check-ignore` as an oracle.

But the same page says `**/logs` owns "any file in a `/logs` directory such
as `/build/logs`" — which *is* recursion into a matched directory.

The one rule that reproduces every example GitHub publishes:

> a pattern also matches everything underneath it, unless its last segment
> contains a wildcard.

| pattern | reaches into subdirectories? | why |
| --- | --- | --- |
| `docs/*` | no | last segment `*` is a wildcard |
| `*.js` | no | last segment `*.js` is a wildcard |
| `apps/` | yes | trailing slash |
| `**/logs` | yes | last segment `logs` is literal |
| `/apps/github` | yes | last segment `github` is literal |

**That rule is inferred, not documented.** GitHub has never published its
matcher. Every row above is pinned by a test, and the gitignore-derived parts
of the matcher are cross-checked against real `git check-ignore` in the test
suite — so the one place this tool deliberately disagrees with git is a
test, not an accident.

## Prior art

The stale-path half of this is well covered:
[mszostok/codeowners-validator](https://github.com/mszostok/codeowners-validator)
has a `files` check, and so do
[jjmschofield/github-codeowners](https://github.com/jjmschofield/github-codeowners)
and [zendesk/setup-check-codeowners](https://github.com/zendesk/setup-check-codeowners).
If you also want owners validated against the GitHub API — a real check, and
one that needs a token — use codeowners-validator; deadowners does not do it
and does not want a token.

codeowners-validator also has an experimental `avoid-shadowing` check. It
asks a different question: whether the entries are ordered least-specific to
most-specific, by comparing patterns to each other. deadowners never compares
two patterns. It asks what happens to your actual files, which is how it can
tell you a rule is dead because *three* later rules split its files between
them, and how it can name the file that proves it.

## Deliberately not done

- **Owner validation.** Whether `@acme/widgets` exists, has members, or has
  write access. It needs a GitHub token and codeowners-validator does it.
- **Unowned files.** The list of files no rule matches. It falls out of the
  same machinery for free, which is exactly why it wants to be its own tool
  with its own opinion about what to do with a monorepo's worth of output.
- **Partly-dead rules.** `docs/*` where `docs/` was meant is the single most
  common CODEOWNERS mistake, and deadowners will not report it, because the
  rule *is* doing something — it owns the files directly under `docs/`. It is
  a good check and it is a different check. `--explain` on a nested file will
  show you.
- **Rewriting your CODEOWNERS.** It tells you which line is dead. Which lines
  you want is not something a tool knows.

## Licence

MIT.
