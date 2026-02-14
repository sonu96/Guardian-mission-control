#!/usr/bin/env node
/**
 * Test Discord Webhook Integration
 *
 * Usage: node scripts/test-discord-webhook.js
 *
 * Requires: DISCORD_WEBHOOK_URL environment variable
 */

import dotenv from 'dotenv';
dotenv.config({ path: '.env.local' });

const DISCORD_WEBHOOK_URL = process.env.DISCORD_WEBHOOK_URL;

if (!DISCORD_WEBHOOK_URL) {
  console.error('❌ DISCORD_WEBHOOK_URL not set in .env.local');
  process.exit(1);
}

async function testWebhook() {
  console.log('🔔 Testing Discord webhook...\n');

  const tests = [
    {
      name: 'Simple Message',
      payload: {
        content: '🚀 **Guardian Mission Control** is online!'
      }
    },
    {
      name: 'Info Alert',
      payload: {
        embeds: [{
          title: 'ℹ️ INFO: Bullish flow detected',
          description: 'AAPL net premium: +$2.3M calls over 7 days',
          color: 0x0099ff, // Blue
          fields: [
            { name: 'Symbol', value: 'AAPL', inline: true },
            { name: 'Agent', value: 'Flow Monitor', inline: true },
            { name: 'Action', value: 'Monitor for directional move', inline: false }
          ],
          timestamp: new Date().toISOString()
        }]
      }
    },
    {
      name: 'Warning Alert',
      payload: {
        embeds: [{
          title: '⚠️ WARNING: High gamma exposure',
          description: 'NVDA showing negative GEX regime',
          color: 0xffa500, // Orange
          fields: [
            { name: 'Symbol', value: 'NVDA', inline: true },
            { name: 'Agent', value: 'GEX Monitor', inline: true },
            { name: 'GEX', value: '-$2.1M', inline: true },
            { name: 'Price', value: '$142.35', inline: true },
            { name: 'Action', value: 'Monitor for volatility expansion', inline: false }
          ],
          timestamp: new Date().toISOString()
        }]
      }
    },
    {
      name: 'Critical Alert',
      payload: {
        embeds: [{
          title: '🔴 CRITICAL: Price approaching short strike',
          description: 'ASTS position requires immediate attention',
          color: 0xff0000, // Red
          fields: [
            { name: 'Position', value: '50/55/65/70 IC', inline: true },
            { name: 'Spot Price', value: '$64.80', inline: true },
            { name: 'Short Strike', value: '$65.00', inline: true },
            { name: 'P&L', value: '+$215 (+23.2%)', inline: true },
            { name: 'DTE', value: '7 days', inline: true },
            { name: 'Action', value: '🚨 Consider rolling up or closing', inline: false }
          ],
          timestamp: new Date().toISOString()
        }]
      }
    }
  ];

  for (const test of tests) {
    console.log(`📤 Sending: ${test.name}`);

    try {
      const response = await fetch(DISCORD_WEBHOOK_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(test.payload)
      });

      if (response.ok) {
        console.log(`✅ ${test.name} sent successfully\n`);
        // Rate limit: Discord allows 30 messages per minute
        await new Promise(resolve => setTimeout(resolve, 2000));
      } else {
        const error = await response.text();
        console.error(`❌ ${test.name} failed:`, error, '\n');
      }
    } catch (error) {
      console.error(`❌ ${test.name} error:`, error.message, '\n');
    }
  }

  console.log('✅ All tests complete! Check your Discord channel.');
}

testWebhook().catch(console.error);
