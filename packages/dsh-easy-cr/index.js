import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PACKAGE_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = join(PACKAGE_DIR, '..', '..')
export const SKILL_DIR = join(REPO_ROOT, 'skills', 'easy-cr')
export const SKILL_PATH = join(SKILL_DIR, 'SKILL.md')

const SKILL_DESCRIPTION = 'Generate an interactive HTML code review organized from top to bottom by business timeline, with comments, replies, themes, filtering, and optional GoLand/IntelliJ IDEA/VS Code semantic references and navigation. Use when the user wants an easy-to-read CR artifact, wants to review a branch or commit in HTML, or asks to configure the editor used by Easy CR.'
const SKILL_WHEN_TO_USE = 'Use when the user names Easy CR, types /easy-cr, asks for an HTML code-review report, or describes a review of the current workspace, a commit, or a branch. No slash subcommand is required; follow the loaded skill and generate the report from the user natural-language scope.'

export const name = 'easy-cr'
export const inject = ['skills']

/**
 * Split a SKILL.md document into frontmatter description and instruction body.
 * @param {string} raw
 */
export function parseSkillDocument(raw) {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/)
  if (!match) {
    throw new Error('easy-cr skill is missing YAML frontmatter')
  }
  const descriptionLine = match[1].match(/^description:\s*(.+)$/m)
  if (descriptionLine === null) {
    throw new Error('easy-cr skill is missing a description')
  }
  return {
    description: descriptionLine[1].trim(),
    content: match[2],
  }
}

/**
 * Load the packaged Easy CR skill from the repository checkout.
 */
export function loadSkillDocument() {
  const parsed = parseSkillDocument(readFileSync(SKILL_PATH, 'utf8'))
  return {
    description: parsed.description || SKILL_DESCRIPTION,
    content: parsed.content,
  }
}

/**
 * Register the embedded Easy CR skill. Do not register a slash command of the
 * same name: `/easy-cr` must stay a user skill invocation so natural-language
 * scope after the token, or a bare `/easy-cr`, reaches the model with the
 * skill body already injected.
 * @param {{ skills: { register(skill: object): unknown } }} ctx
 */
export function apply(ctx) {
  const skill = loadSkillDocument()
  ctx.skills.register({
    name: 'easy-cr',
    description: skill.description,
    whenToUse: SKILL_WHEN_TO_USE,
    source: 'runtime',
    resourceBase: { kind: 'directory', path: SKILL_DIR },
    path: SKILL_PATH,
    content: skill.content,
  })
}
