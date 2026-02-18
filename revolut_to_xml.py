#!/usr/bin/env python3
"""Convert Revolut Business CSV transaction statement to CSOB camt.053.001.02 XML."""

import argparse
import csv
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent


NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = f"{NAMESPACE} camt.053.001.02.xsd"

ACCOUNT_OWNER = "Nethemba s.r.o."
ACCOUNT_ADDR_LINE1 = "Grosslingova 2503/62"
ACCOUNT_ADDR_LINE2 = "Bratislava - St. Mesto 81109 SK"

SERVICER_BIC = "REVOLT21"
SERVICER_NAME = "Revolut Bank UAB"
SERVICER_COUNTRY = "LT"

# BkTxCd codes per transaction type
TX_CODES = {
    "CARD_PAYMENT": "30000301000",
    "TOPUP":        "10000405000",
    "FEE":          "40000605000",
    "TRANSFER":     "20000405000",
}

TX_INFO = {
    "CARD_PAYMENT": "Kartova transakcia",
    "TOPUP":        "Prijata platba",
    "FEE":          "Poplatok",
    "TRANSFER":     "Odchadzajuca platba",
}


def parse_date(s):
    """Parse date string like '2026-01-15' or '2026-02-14'."""
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def dec(s):
    """Parse a decimal string, return Decimal."""
    s = s.strip()
    if not s:
        return Decimal("0")
    return Decimal(s)


def fmt_amt(d):
    """Format Decimal to 2 decimal places string."""
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def extract_sender_name(description):
    """Extract sender name from TOPUP description like 'Money added from SOME NAME'."""
    m = re.match(r"Money added from (.+)", description, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return description


def read_csv(path):
    """Read Revolut CSV and return list of row dicts, sorted chronologically (oldest first)."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    # CSV is newest-first; reverse to chronological order
    rows.reverse()
    return rows


def build_xml(rows, iban):
    """Build the camt.053.001.02 XML tree from parsed CSV rows."""
    if not rows:
        print("Error: no transactions found in CSV", file=sys.stderr)
        sys.exit(1)

    # Determine date range from completed dates
    dates = [parse_date(r["Date completed (UTC)"]) for r in rows]
    first_date = min(dates)
    last_date = max(dates)

    # Compute balances
    # rows are chronological (oldest first)
    # Balance column = balance AFTER the transaction
    first_balance_after = dec(rows[0]["Balance"])
    first_total_amount = dec(rows[0]["Total amount"])
    opening_balance = first_balance_after - first_total_amount

    last_balance_after = dec(rows[-1]["Balance"])
    closing_balance = last_balance_after

    # Build XML
    root = Element("Document")
    root.set("xmlns", NAMESPACE)
    root.set("xmlns:xsi", XSI)
    root.set("xsi:schemaLocation", SCHEMA_LOCATION)

    bk = SubElement(root, "BkToCstmrStmt")

    # GrpHdr
    grp = SubElement(bk, "GrpHdr")
    now = datetime.now(timezone.utc)
    msg_id = f"REVOLT21-{iban[-4:]}-{now.strftime('%y%m%d')}-{now.strftime('%H%M%S')}"
    SubElement(grp, "MsgId").text = msg_id
    SubElement(grp, "CreDtTm").text = now.strftime("%Y-%m-%dT%H:%M:%S.0+00:00")
    pgn = SubElement(grp, "MsgPgntn")
    SubElement(pgn, "PgNb").text = "1"
    SubElement(pgn, "LastPgInd").text = "true"
    SubElement(grp, "AddtlInf").text = "mesacny"

    # Stmt
    stmt = SubElement(bk, "Stmt")
    SubElement(stmt, "Id").text = f"{iban}-{first_date.strftime('%y%m%d')}-{last_date.strftime('%y%m%d')}"
    SubElement(stmt, "ElctrncSeqNb").text = "1"
    SubElement(stmt, "LglSeqNb").text = "1"
    SubElement(stmt, "CreDtTm").text = now.strftime("%Y-%m-%dT%H:%M:%S.0+00:00")

    fr_to = SubElement(stmt, "FrToDt")
    SubElement(fr_to, "FrDtTm").text = f"{first_date.isoformat()}T00:00:00.0+00:00"
    SubElement(fr_to, "ToDtTm").text = f"{last_date.isoformat()}T23:59:59.9+00:00"

    # Acct
    acct = SubElement(stmt, "Acct")
    acct_id = SubElement(acct, "Id")
    SubElement(acct_id, "IBAN").text = iban
    acct_tp = SubElement(acct, "Tp")
    SubElement(acct_tp, "Cd").text = "CACC"
    SubElement(acct, "Ccy").text = "EUR"
    SubElement(acct, "Nm").text = ACCOUNT_OWNER
    ownr = SubElement(acct, "Ownr")
    SubElement(ownr, "Nm").text = ACCOUNT_OWNER
    ownr_addr = SubElement(ownr, "PstlAdr")
    SubElement(ownr_addr, "AdrLine").text = ACCOUNT_ADDR_LINE1
    SubElement(ownr_addr, "AdrLine").text = ACCOUNT_ADDR_LINE2
    SubElement(ownr_addr, "AdrLine").text = "LITHUANIA"

    svcr = SubElement(acct, "Svcr")
    svcr_fi = SubElement(svcr, "FinInstnId")
    SubElement(svcr_fi, "BIC").text = SERVICER_BIC
    SubElement(svcr_fi, "Nm").text = SERVICER_NAME
    svcr_addr = SubElement(svcr_fi, "PstlAdr")
    SubElement(svcr_addr, "Ctry").text = SERVICER_COUNTRY

    # Balances
    _add_balance(stmt, "PRCD", opening_balance, first_date)
    _add_balance(stmt, "CLBD", closing_balance, last_date)

    # TxsSummry
    total_credit = Decimal("0")
    total_debit = Decimal("0")
    count_credit = 0
    count_debit = 0
    for r in rows:
        amt = dec(r["Total amount"])
        if amt >= 0:
            total_credit += amt
            count_credit += 1
        else:
            total_debit += abs(amt)
            count_debit += 1

    txs = SubElement(stmt, "TxsSummry")
    ttl = SubElement(txs, "TtlNtries")
    SubElement(ttl, "NbOfNtries").text = str(len(rows))
    SubElement(ttl, "Sum").text = fmt_amt(total_credit + total_debit)
    net = total_credit - total_debit
    SubElement(ttl, "TtlNetNtryAmt").text = fmt_amt(abs(net))
    SubElement(ttl, "CdtDbtInd").text = "CRDT" if net >= 0 else "DBIT"

    ttl_cdt = SubElement(txs, "TtlCdtNtries")
    SubElement(ttl_cdt, "NbOfNtries").text = str(count_credit)
    SubElement(ttl_cdt, "Sum").text = fmt_amt(total_credit)

    ttl_dbt = SubElement(txs, "TtlDbtNtries")
    SubElement(ttl_dbt, "NbOfNtries").text = str(count_debit)
    SubElement(ttl_dbt, "Sum").text = fmt_amt(total_debit)

    # Entries
    for idx, r in enumerate(rows, start=1):
        _add_entry(stmt, r, idx, iban)

    return ElementTree(root)


def _add_balance(stmt, code, amount, dt):
    """Add a Bal element (PRCD or CLBD)."""
    bal = SubElement(stmt, "Bal")
    tp = SubElement(bal, "Tp")
    cd_or = SubElement(tp, "CdOrPrtry")
    SubElement(cd_or, "Cd").text = code
    amt_el = SubElement(bal, "Amt")
    amt_el.set("Ccy", "EUR")
    amt_el.text = fmt_amt(abs(amount))
    SubElement(bal, "CdtDbtInd").text = "CRDT" if amount >= 0 else "DBIT"
    dt_el = SubElement(bal, "Dt")
    SubElement(dt_el, "Dt").text = dt.isoformat()


def _add_entry(stmt, row, seq, iban):
    """Add an Ntry element for one transaction."""
    total_amount = dec(row["Total amount"])
    is_credit = total_amount >= 0
    abs_amount = abs(total_amount)
    completed_date = parse_date(row["Date completed (UTC)"])
    tx_type = row["Type"]
    tx_code = TX_CODES.get(tx_type, "99999999999")
    tx_info = TX_INFO.get(tx_type, tx_type)
    description = row.get("Description", "").strip()
    reference = row.get("Reference", "").strip()
    tx_id = row.get("ID", "").strip()
    payment_ccy = row.get("Payment currency", "EUR").strip()

    ntry = SubElement(stmt, "Ntry")
    SubElement(ntry, "NtryRef").text = str(seq)
    amt_el = SubElement(ntry, "Amt")
    amt_el.set("Ccy", payment_ccy)
    amt_el.text = fmt_amt(abs_amount)
    SubElement(ntry, "CdtDbtInd").text = "CRDT" if is_credit else "DBIT"
    SubElement(ntry, "RvslInd").text = "false"
    SubElement(ntry, "Sts").text = "BOOK"

    bkg_dt = SubElement(ntry, "BookgDt")
    SubElement(bkg_dt, "Dt").text = completed_date.isoformat()
    val_dt = SubElement(ntry, "ValDt")
    SubElement(val_dt, "Dt").text = completed_date.isoformat()

    bk_tx = SubElement(ntry, "BkTxCd")
    prtry = SubElement(bk_tx, "Prtry")
    SubElement(prtry, "Cd").text = tx_code
    SubElement(prtry, "Issr").text = "SBA"

    # NtryDtls
    dtls = SubElement(ntry, "NtryDtls")
    tx_dtls = SubElement(dtls, "TxDtls")

    # Refs
    refs = SubElement(tx_dtls, "Refs")
    SubElement(refs, "AcctSvcrRef").text = str(seq)
    SubElement(refs, "TxId").text = tx_id

    # AmtDtls
    amt_dtls = SubElement(tx_dtls, "AmtDtls")
    orig_ccy = row.get("Orig currency", "").strip()
    orig_amount_str = row.get("Orig amount", "").strip()
    xchg_rate = row.get("Exchange rate", "").strip()

    if orig_ccy and orig_ccy != payment_ccy and orig_amount_str and xchg_rate:
        # Foreign currency transaction
        orig_amount = dec(orig_amount_str)
        instd = SubElement(amt_dtls, "InstdAmt")
        instd_amt = SubElement(instd, "Amt")
        instd_amt.set("Ccy", orig_ccy)
        instd_amt.text = fmt_amt(abs(orig_amount))

        cntr = SubElement(amt_dtls, "CntrValAmt")
        cntr_amt = SubElement(cntr, "Amt")
        cntr_amt.set("Ccy", payment_ccy)
        # Use Amount (before fees) as counter value
        amount_before_fees = abs(dec(row.get("Amount", "0")))
        cntr_amt.text = fmt_amt(amount_before_fees)
        xchg = SubElement(cntr, "CcyXchg")
        SubElement(xchg, "SrcCcy").text = orig_ccy
        SubElement(xchg, "TrgtCcy").text = payment_ccy
        SubElement(xchg, "XchgRate").text = xchg_rate
    else:
        # Same currency
        instd = SubElement(amt_dtls, "InstdAmt")
        instd_amt = SubElement(instd, "Amt")
        instd_amt.set("Ccy", payment_ccy)
        instd_amt.text = fmt_amt(abs_amount)

    # BkTxCd inside TxDtls
    bk_tx2 = SubElement(tx_dtls, "BkTxCd")
    prtry2 = SubElement(bk_tx2, "Prtry")
    SubElement(prtry2, "Cd").text = tx_code
    SubElement(prtry2, "Issr").text = "SBA"

    # RltdPties
    _add_related_parties(tx_dtls, row, is_credit, iban)

    # RltdAgts
    _add_related_agents(tx_dtls, row, is_credit)

    # RmtInf
    rmt = SubElement(tx_dtls, "RmtInf")
    rmt_parts = []
    if description:
        rmt_parts.append(description)
    if reference:
        rmt_parts.append(reference)
    SubElement(rmt, "Ustrd").text = "; ".join(rmt_parts) if rmt_parts else tx_type

    # AddtlTxInf
    SubElement(tx_dtls, "AddtlTxInf").text = tx_info


def _add_related_parties(tx_dtls, row, is_credit, iban):
    """Add RltdPties element based on transaction direction."""
    parties = SubElement(tx_dtls, "RltdPties")

    if is_credit:
        # CRDT: Dbtr = sender, Cdtr = us (Nethemba)
        sender_name = extract_sender_name(row.get("Description", ""))
        dbtr = SubElement(parties, "Dbtr")
        SubElement(dbtr, "Nm").text = sender_name

        beneficiary_iban = row.get("Beneficiary IBAN", "").strip()
        beneficiary_bic = row.get("Beneficiary BIC", "").strip()
        if beneficiary_iban:
            dbtr_acct = SubElement(parties, "DbtrAcct")
            dbtr_acct_id = SubElement(dbtr_acct, "Id")
            SubElement(dbtr_acct_id, "IBAN").text = beneficiary_iban
            SubElement(dbtr_acct, "Nm").text = sender_name

        cdtr = SubElement(parties, "Cdtr")
        SubElement(cdtr, "Nm").text = ACCOUNT_OWNER
        cdtr_addr = SubElement(cdtr, "PstlAdr")
        SubElement(cdtr_addr, "AdrLine").text = ACCOUNT_ADDR_LINE1
        SubElement(cdtr_addr, "AdrLine").text = ACCOUNT_ADDR_LINE2

        cdtr_acct = SubElement(parties, "CdtrAcct")
        cdtr_acct_id = SubElement(cdtr_acct, "Id")
        SubElement(cdtr_acct_id, "IBAN").text = iban
        SubElement(cdtr_acct, "Nm").text = ACCOUNT_OWNER
    else:
        # DBIT: Dbtr = us (Nethemba), no Cdtr
        dbtr = SubElement(parties, "Dbtr")
        SubElement(dbtr, "Nm").text = ACCOUNT_OWNER
        dbtr_addr = SubElement(dbtr, "PstlAdr")
        SubElement(dbtr_addr, "AdrLine").text = ACCOUNT_ADDR_LINE1
        SubElement(dbtr_addr, "AdrLine").text = ACCOUNT_ADDR_LINE2

        dbtr_acct = SubElement(parties, "DbtrAcct")
        dbtr_acct_id = SubElement(dbtr_acct, "Id")
        SubElement(dbtr_acct_id, "IBAN").text = iban
        SubElement(dbtr_acct, "Nm").text = ACCOUNT_OWNER


def _add_related_agents(tx_dtls, row, is_credit):
    """Add RltdAgts element."""
    agents = SubElement(tx_dtls, "RltdAgts")

    if is_credit:
        # CRDT: DbtrAgt = sender's bank (use Revolut as default), CdtrAgt = Revolut
        beneficiary_bic = row.get("Beneficiary BIC", "").strip()
        dbtr_agt = SubElement(agents, "DbtrAgt")
        dbtr_fi = SubElement(dbtr_agt, "FinInstnId")
        if beneficiary_bic:
            SubElement(dbtr_fi, "BIC").text = beneficiary_bic
        else:
            SubElement(dbtr_fi, "BIC").text = SERVICER_BIC
            SubElement(dbtr_fi, "Nm").text = SERVICER_NAME

        cdtr_agt = SubElement(agents, "CdtrAgt")
        cdtr_fi = SubElement(cdtr_agt, "FinInstnId")
        SubElement(cdtr_fi, "BIC").text = SERVICER_BIC
        SubElement(cdtr_fi, "Nm").text = SERVICER_NAME
    else:
        # DBIT: DbtrAgt = Revolut
        dbtr_agt = SubElement(agents, "DbtrAgt")
        dbtr_fi = SubElement(dbtr_agt, "FinInstnId")
        SubElement(dbtr_fi, "BIC").text = SERVICER_BIC
        SubElement(dbtr_fi, "Nm").text = SERVICER_NAME


def main():
    parser = argparse.ArgumentParser(
        description="Convert Revolut Business CSV to CSOB camt.053.001.02 XML"
    )
    parser.add_argument("--iban", required=True, help="Revolut Business IBAN")
    parser.add_argument("--input", required=True, help="Path to Revolut CSV file")
    parser.add_argument("--output", help="Output XML path (auto-generated if omitted)")
    args = parser.parse_args()

    rows = read_csv(args.input)
    if not rows:
        print("Error: no transactions found in CSV", file=sys.stderr)
        sys.exit(1)

    tree = build_xml(rows, args.iban)

    if args.output:
        output_path = args.output
    else:
        dates = [parse_date(r["Date completed (UTC)"]) for r in rows]
        first_date = min(dates)
        last_date = max(dates)
        output_path = f"{args.iban}_{first_date.strftime('%Y%m%d')}_{last_date.strftime('%Y%m%d')}.xml"

    indent(tree, space="  ")

    with open(output_path, "wb") as f:
        tree.write(f, encoding="UTF-8", xml_declaration=True)

    # Count summary
    credits = sum(1 for r in rows if dec(r["Total amount"]) >= 0)
    debits = len(rows) - credits
    print(f"Converted {len(rows)} transactions ({credits} CRDT, {debits} DBIT) -> {output_path}")


if __name__ == "__main__":
    main()
