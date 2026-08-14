import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apply, loadSkillDocument, name, parseSkillDocument, SKILL_DIR, SKILL_PATH } from './index.js'

const packageDir = dirname(fileURLToPath(import.meta.url))
const manifest = JSON.parse(readFileSync(join(packageDir, 'package.json'), 'utf8'))
const patch = readFileSync(join(packageDir, 'cordis.patch.yml'), 'utf8')
const skill = loadSkillDocument()

assert.equal(manifest.name, 'dsh-easy-cr')
assert.equal(manifest.dsh.bundle.patch, './cordis.patch.yml')
assert.match(patch, /id: easy-cr/)
assert.match(patch, /name: dsh-easy-cr/)
assert.equal(name, 'easy-cr')
assert.ok(SKILL_PATH.endsWith(join('skills', 'easy-cr', 'SKILL.md')))
assert.match(skill.description, /interactive HTML code review/)
assert.match(skill.content, /# Easy CR/)
assert.doesNotMatch(skill.content, /^---/m)

const parsed = parseSkillDocument('---\nname: easy-cr\ndescription: Demo skill\n---\n\nBody.\n')
assert.equal(parsed.description, 'Demo skill')
assert.equal(parsed.content, '\nBody.\n')
assert.throws(() => parseSkillDocument('# no frontmatter\n'), /missing YAML frontmatter/)

const registered = { skills: [], commands: [] }
apply({
  skills: { register(skill) { registered.skills.push(skill) } },
  commands: { register(command) { registered.commands.push(command) } },
})

assert.equal(registered.skills.length, 1)
assert.equal(registered.skills[0].name, 'easy-cr')
assert.equal(registered.skills[0].source, 'runtime')
assert.match(registered.skills[0].whenToUse, /No slash subcommand/)
assert.deepEqual(registered.skills[0].resourceBase, { kind: 'directory', path: SKILL_DIR })
assert.equal(registered.commands.length, 0)

console.log('dsh-easy-cr plugin checks passed')
