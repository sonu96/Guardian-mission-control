#!/usr/bin/env node
/**
 * Test Obsidian CLI Integration
 *
 * Tests all Obsidian logging functions to verify integration works
 *
 * Usage: node scripts/test-obsidian-integration.js
 */

import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

const VAULT = process.env.OBSIDIAN_VAULT || 'TradingVault';

async function runTest(name, command) {
  console.log(`\n📝 Test: ${name}`);
  console.log(`Command: ${command}`);

  try {
    const { stdout, stderr } = await execAsync(command);
    if (stdout) console.log('Output:', stdout);
    if (stderr) console.warn('Warning:', stderr);
    console.log('✅ PASSED');
    return true;
  } catch (error) {
    console.error('❌ FAILED:', error.message);
    return false;
  }
}

async function main() {
  console.log('🔍 Obsidian CLI Integration Tests\n');
  console.log(`Vault: ${VAULT}`);
  console.log('---');

  const tests = [
    {
      name: 'Check Obsidian CLI installed',
      command: 'which obsidian',
    },
    {
      name: 'Open daily note',
      command: `obsidian daily vault="${VAULT}"`,
    },
    {
      name: 'Append to daily note',
      command: `obsidian daily:append vault="${VAULT}" content="## Test Entry\\n- Test successful at $(date +%H:%M)"`,
    },
    {
      name: 'Create test position note',
      command: `obsidian create vault="${VAULT}" name="Positions/TEST-2026-02-20-IC" content="# Test Position\\n\\nThis is a test." silent`,
    },
    {
      name: 'Append to position note',
      command: `obsidian append vault="${VAULT}" file="Positions/TEST-2026-02-20-IC.md" content="\\n## Update\\n- Test update successful"`,
    },
    {
      name: 'Search vault',
      command: `obsidian search vault="${VAULT}" query="TEST"`,
    },
    {
      name: 'List tags',
      command: `obsidian tags vault="${VAULT}" counts`,
    },
  ];

  let passed = 0;
  let failed = 0;

  for (const test of tests) {
    const result = await runTest(test.name, test.command);
    if (result) {
      passed++;
    } else {
      failed++;
    }

    // Rate limit
    await new Promise(resolve => setTimeout(resolve, 1000));
  }

  console.log('\n---');
  console.log('📊 Test Results:');
  console.log(`✅ Passed: ${passed}/${tests.length}`);
  console.log(`❌ Failed: ${failed}/${tests.length}`);

  if (failed === 0) {
    console.log('\n🎉 All tests passed! Obsidian integration ready.');
  } else {
    console.log('\n⚠️  Some tests failed. Check OBSIDIAN_SETUP.md for configuration.');
  }

  process.exit(failed > 0 ? 1 : 0);
}

main().catch(console.error);
