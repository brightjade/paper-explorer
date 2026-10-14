/**
 * Behavioural tests for the github-script body in the `Apply it` step of
 * `.github/workflows/monthly.yml`.
 *
 *   node tests/workflow/monthly-workflow.test.js
 *
 * The decision of what to say about a sweep (notify, blind or close) now lives
 * in `ppr/report.py` and is covered by pytest. What remains in the workflow is
 * a thin executor, but it still owns the notification guarantees: an edit to a
 * title or body notifies nobody, so an open issue must be updated AND commented
 * on; a blind run may only comment, never close; a close must comment before it
 * closes. Those are one-line mistakes, so the script is extracted from the
 * workflow file itself (never a copy, which would drift) and driven the way
 * `actions/github-script` drives it: the body wrapped in an async function
 * receiving github, context, core and require, with a recording stub for the
 * issues REST surface.
 *
 * Node only, no dependencies -- the YAML block is extracted by indentation
 * rather than by parsing YAML.
 */

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const WORKFLOW = path.join(__dirname, '..', '..', '.github', 'workflows', 'monthly.yml');

/** Pull the `script: |` literal block out of the workflow, dedented. */
function extractScript(yamlPath) {
  const lines = fs.readFileSync(yamlPath, 'utf8').split('\n');
  const start = lines.findIndex((l) => /^\s*script:\s*\|\s*$/.test(l));
  assert.notStrictEqual(start, -1, `no "script: |" block in ${yamlPath}`);

  const openIndent = lines[start].match(/^\s*/)[0].length;
  const body = [];
  for (const line of lines.slice(start + 1)) {
    if (line.trim() === '') {
      body.push('');
      continue;
    }
    if (line.match(/^\s*/)[0].length <= openIndent) break;
    body.push(line);
  }
  const strip = Math.min(
    ...body.filter((l) => l.trim()).map((l) => l.match(/^\s*/)[0].length)
  );
  return body.map((l) => l.slice(strip)).join('\n');
}

const SRC = extractScript(WORKFLOW);
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const NOTIFY = {
  action: 'notify',
  title: 'New accepted-paper lists: usenix_security_2026 (381)',
  body: '## Ready to register\n\n- `usenix_security_2026` — 381 papers',
  comment: 'Sweep on 2026-10-03: 1 new list(s) ready to register.',
};

const BLIND = { action: 'blind', comment: 'Sweep could not probe enough venues; leaving open.' };

const CLOSE = { action: 'close', comment: 'Clean sweep, nothing found. Closing.' };

const openIssue = (number) => ({ number, title: `old ${number}`, state: 'open' });

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

function makeGithub(openIssues) {
  const calls = [];
  const record = (name) => async (args) => {
    calls.push({ name, args });
    return { data: { number: 99 } };
  };
  return {
    calls,
    api: {
      rest: {
        issues: {
          listForRepo: async (args) => {
            calls.push({ name: 'listForRepo', args });
            return { data: openIssues };
          },
          create: record('create'),
          update: record('update'),
          createComment: record('createComment'),
        },
      },
    },
  };
}

/** Run the workflow script against one action, in a scratch directory. */
async function run({ action, openIssues = [] }) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'monthly-wf-'));
  const cwd = process.cwd();
  const logs = [];
  const gh = makeGithub(openIssues);
  try {
    process.chdir(dir);
    fs.writeFileSync('action.json', JSON.stringify(action));
    await new AsyncFunction('github', 'context', 'core', 'require', SRC)(
      gh.api,
      { repo: { owner: 'o', repo: 'r' } },
      { info: (m) => logs.push(m) },
      require
    );
  } finally {
    process.chdir(cwd);
    fs.rmSync(dir, { recursive: true, force: true });
  }
  return { calls: gh.calls, logs };
}

/** The recorded REST calls minus the listForRepo lookup, as `name(issue)` pairs. */
const writes = (r) => r.calls.filter((c) => c.name !== 'listForRepo');

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

const CASES = [
  {
    name: 'notify with no open issue opens one labelled issue and no comment',
    input: { action: NOTIFY, openIssues: [] },
    check(r) {
      assert.deepStrictEqual(writes(r).map((c) => c.name), ['create']);
      assert.deepStrictEqual(writes(r)[0].args.labels, ['new-conferences']);
      assert.strictEqual(writes(r)[0].args.title, NOTIFY.title);
      assert.strictEqual(writes(r)[0].args.body, NOTIFY.body);
    },
  },
  {
    name: 'notify with an open issue updates it AND comments, never creates',
    why: 'a title or body edit notifies nobody; the comment is what reaches a human',
    input: { action: NOTIFY, openIssues: [openIssue(7)] },
    check(r) {
      assert.deepStrictEqual(writes(r).map((c) => c.name), ['update', 'createComment']);
      assert.deepStrictEqual(writes(r)[0].args, {
        owner: 'o', repo: 'r', issue_number: 7, title: NOTIFY.title, body: NOTIFY.body,
      });
      assert.deepStrictEqual(writes(r)[1].args, {
        owner: 'o', repo: 'r', issue_number: 7, body: NOTIFY.comment,
      });
    },
  },
  {
    name: 'blind comments on every open issue and touches nothing else',
    why: 'a blind sweep proves nothing, so it must never close or retitle',
    input: { action: BLIND, openIssues: [openIssue(3), openIssue(5)] },
    check(r) {
      assert.deepStrictEqual(writes(r).map((c) => c.name), ['createComment', 'createComment']);
      assert.deepStrictEqual(
        writes(r).map((c) => c.args.issue_number), [3, 5]
      );
      for (const c of writes(r)) assert.strictEqual(c.args.body, BLIND.comment);
    },
  },
  {
    name: 'blind with no open issue makes no writes',
    input: { action: BLIND, openIssues: [] },
    check(r) {
      assert.deepStrictEqual(writes(r), []);
    },
  },
  {
    name: 'close comments then closes every open issue',
    why: 'the comment must land before the issue is closed, or the close is silent',
    input: { action: CLOSE, openIssues: [openIssue(3), openIssue(5)] },
    check(r) {
      assert.deepStrictEqual(
        writes(r).map((c) => `${c.name}#${c.args.issue_number}`),
        ['createComment#3', 'update#3', 'createComment#5', 'update#5']
      );
      for (const c of writes(r).filter((w) => w.name === 'update')) {
        assert.strictEqual(c.args.state, 'closed');
        assert.strictEqual(c.args.state_reason, 'completed');
      }
    },
  },
  {
    name: 'close with no open issue makes no writes',
    input: { action: CLOSE, openIssues: [] },
    check(r) {
      assert.deepStrictEqual(writes(r), []);
    },
  },
  {
    name: 'the open-issue lookup filters on state open and the new-conferences label',
    input: { action: NOTIFY, openIssues: [] },
    check(r) {
      const lookup = r.calls.find((c) => c.name === 'listForRepo');
      assert.ok(lookup, 'listForRepo must be called');
      assert.strictEqual(lookup.args.state, 'open');
      assert.strictEqual(lookup.args.labels, 'new-conferences');
    },
  },
];

(async () => {
  let failed = 0;
  for (const c of CASES) {
    try {
      c.check(await run(c.input));
      console.log(`  PASS  ${c.name}`);
    } catch (err) {
      failed += 1;
      console.log(`  FAIL  ${c.name}`);
      if (c.why) console.log(`        why it matters: ${c.why}`);
      console.log(`        ${err.message}`);
    }
  }
  console.log(`\n${CASES.length - failed}/${CASES.length} workflow cases passed.`);
  process.exit(failed ? 1 : 0);
})();
