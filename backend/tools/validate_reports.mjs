import Ajv2020 from 'ajv/dist/2020.js'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
const schema = JSON.parse(readFileSync('docs/schema/report-content.schema.json', 'utf8'))
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema)
const directory = resolve(process.argv[2] ?? 'docs/fixtures/report')
for (const file of readdirSync(directory).filter(name => name.endsWith('.json'))) {
  if (!validate(JSON.parse(readFileSync(resolve(directory, file), 'utf8')))) {
    console.error(file, validate.errors)
    process.exit(1)
  }
  console.log(`Report contract passed: ${file}`)
}
