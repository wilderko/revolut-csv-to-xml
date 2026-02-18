# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repository holds financial transaction data for processing/conversion between formats:

- **Revolut CSV**: Business transaction statement export (`transaction-statement_*.csv`) with columns: dates, ID, type (CARD_PAYMENT, TOPUP, FEE, TRANSFER), state, description, payer, card info, currencies, amounts, fees, balance, MCC codes
- **CAMT.053 XML**: Slovak bank statement in ISO 20022 camt.053.001.02 format (CSOB bank, IBAN SK74..., account holder Nethemba s.r.o.)

## Data Details

- Currency: primarily EUR, with some transactions in CZK (auto-converted)
- CSV fields of note: `Orig currency`/`Orig amount` vs `Payment currency`/`Amount`/`Total amount` (total includes fees), `Exchange rate`, `MCC` (merchant category code)
- XML follows ISO 20022 BkToCstmrStmt schema with entries containing booking/value dates, amounts, debtor/creditor info, and remittance references

## No Build/Test Infrastructure

This repository currently has no code, build system, or tests. It is a data-only workspace.
