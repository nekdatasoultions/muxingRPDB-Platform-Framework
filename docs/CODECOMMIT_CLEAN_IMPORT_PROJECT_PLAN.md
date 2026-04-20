# CodeCommit Clean Import Project Plan

## Purpose

Create a clean, standalone AWS CodeCommit copy of the RPDB platform repo without
mirroring GitHub, without copying existing `.git` metadata, and without exposing
local workstation paths or chat artifacts.

## Scope

This plan imports the current verified RPDB code state into a new CodeCommit
repository as a fresh initial commit.

In scope:

- Export tracked files only from the verified RPDB repo state.
- Create a new empty CodeCommit repository.
- Initialize a fresh temporary Git repository from the clean export.
- Add only the CodeCommit remote.
- Push a new `main` branch to CodeCommit.
- Clone CodeCommit into a separate verification folder.
- Verify the CodeCommit clone is clean and independent.

Out of scope:

- CodePipeline.
- Live node deployment.
- Customer apply.
- MUXER3 changes.
- GitHub mirroring.
- Reusing existing `.git` history or remotes.

## Guardrails

- Do not copy `.git` from the current repo.
- Do not add the GitHub remote to the CodeCommit import repo.
- Do not mirror from GitHub.
- Do not include local build output, caches, temp folders, SSH material, or local
  metadata.
- Do not include local workstation path references.
- Do not include chat exports or old-solution scale-test notes.
- Do not touch live AWS nodes.
- Do not touch the legacy MUXER3 repo.

## Phase 1: Pre-Import Verification

Goal: prove the source state is clean before exporting it.

Steps:

1. Confirm the RPDB working tree is clean.
2. Confirm the current branch and commit are the intended baseline.
3. Run the full repo verification suite.
4. Run the local-reference scrub check.
5. Stop and fix any failure before continuing.

Validation:

- `git status --short --branch` shows no uncommitted changes.
- Full repo verification passes.
- No local workspace references, chat artifact names, or old-solution notes are
  found in tracked files.

## Phase 2: Create Clean Export

Goal: create a source tree without Git metadata.

Steps:

1. Create a temporary clean import folder.
2. Export tracked files only from current `HEAD`.
3. Extract/copy the exported files into the temporary folder.
4. Confirm `.git` is not present in the temporary folder.

Validation:

- Temporary folder contains project files.
- Temporary folder does not contain `.git`.
- Temporary folder does not contain build output, caches, temp folders, SSH
  material, or local metadata.

## Phase 3: Create Empty CodeCommit Repo

Goal: create the destination repository with no relationship to GitHub.

Steps:

1. Create a new empty CodeCommit repo.
2. Use a clear repo name, for example `muxingRPDB-Platform-Framework`.
3. Record the AWS region and repository clone URL.

Validation:

- CodeCommit repo exists.
- CodeCommit repo is empty before import.
- No GitHub integration or mirror is configured.

## Phase 4: Initialize Fresh Import Repo

Goal: create an independent Git history for CodeCommit.

Steps:

1. In the temporary clean import folder, run `git init -b main`.
2. Add only the CodeCommit remote as `origin`.
3. Confirm `git remote -v` lists only CodeCommit.
4. Stage all files.
5. Commit with message `Initial RPDB platform import`.

Validation:

- Import repo has a fresh initial commit.
- Import repo remote list contains only CodeCommit.
- Import repo does not contain the old GitHub remote.

## Phase 5: Push To CodeCommit

Goal: publish the clean standalone import.

Steps:

1. Push `main` to CodeCommit.
2. Confirm the pushed commit exists in CodeCommit.
3. Record the CodeCommit commit SHA.

Validation:

- CodeCommit `main` exists.
- CodeCommit `main` points to the fresh initial import commit.
- CodeCommit contains no imported GitHub history.

## Phase 6: Independent Verification Clone

Goal: prove CodeCommit is clean from a new clone.

Steps:

1. Clone CodeCommit into a separate verification folder.
2. Confirm `git remote -v` lists only CodeCommit.
3. Confirm there are no local workspace path references.
4. Confirm there are no chat artifacts.
5. Confirm there are no old-solution scale-test notes.
6. Run the full repo verification suite from the CodeCommit clone.

Validation:

- Verification clone has only the CodeCommit remote.
- Local-reference scrub check passes.
- Full repo verification passes.
- No live AWS nodes are touched.

## Phase 7: Acceptance Gate

Goal: capture the import result and stop before pipeline or deploy work.

Record:

- CodeCommit repository name.
- AWS region.
- CodeCommit clone URL.
- CodeCommit commit SHA.
- Verification clone location.
- Verification command results.

Definition of done:

- CodeCommit has a clean standalone RPDB repo.
- CodeCommit does not know about GitHub or the current local repo.
- Verification clone passes full repo verification.
- No CodePipeline exists yet.
- No live nodes were touched.
- No MUXER3 repo changes were made.

