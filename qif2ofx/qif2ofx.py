import argparse
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from glob import glob
from xml.dom import minidom

import ofxtools.models as m
from ofxtools.header import make_header
from ofxtools.utils import UTC

from .qif import QIFFile


def qif_to_stmttrn(qif_file):
    stmttrns = []
    for transaction in qif_file.transactions:
        trntype = 'DEBIT' if transaction.amount < 0 else 'CREDIT'
        dtposted = transaction.date.replace(tzinfo=UTC)
        trnamt = transaction.amount
        name = transaction.payee
        fitid = '{}{}{}'.format(dtposted, trnamt, name)
        stmttrns.append(m.STMTTRN(
            dtposted=dtposted,
            fitid=fitid,
            trnamt=trnamt,
            trntype=trntype,
            name=name,
            memo=transaction.reference
        ))
    return stmttrns


def genofx(qif_file, fileDir, currency, acctid, trnuid, org, balance):
    trans = qif_to_stmttrn(qif_file)

    balamt = Decimal(balance) + qif_file.balance()
    ledgerbal = m.LEDGERBAL(balamt=balamt,
                            dtasof=qif_file.last_transaction_date())
    ccacctfrom = m.CCACCTFROM(acctid=acctid)  # OFX Section 11.3.1
    banktranlist = m.BANKTRANLIST(*trans, dtstart=datetime(2019, 1, 1, 12, tzinfo=UTC),
                                  dtend=datetime(2018, 1, 1, 12, tzinfo=UTC))
    status = m.STATUS(code=0, severity='INFO')
    ccstmtrs = m.CCSTMTRS(curdef=currency, ccacctfrom=ccacctfrom, banktranlist=banktranlist, ledgerbal=ledgerbal)
    ccstmttrnrs = m.CCSTMTTRNRS(trnuid=trnuid, status=status, ccstmtrs=ccstmtrs)
    ccmsgsrsv1 = m.CREDITCARDMSGSRSV1(ccstmttrnrs)
    fi = m.FI(org=org, fid='666')  # Required for Quicken compatibility
    sonrs = m.SONRS(status=status,
                    dtserver=datetime.now(tz=UTC),
                    language='ENG', fi=fi)
    signonmsgs = m.SIGNONMSGSRSV1(sonrs=sonrs)
    ofx = m.OFX(signonmsgsrsv1=signonmsgs, creditcardmsgsrsv1=ccmsgsrsv1)
    root = ofx.to_etree()
    message = ET.tostring(root).decode()
    pretty_message = minidom.parseString(message).toprettyxml()
    header = str(make_header(version=220))

    file = os.path.splitext(fileDir)[0] + '.ofx'  # /create ofx file
    print("Creating ofx file: " + file)
    with open(file, 'w') as filetowrite:
        filetowrite.write(header + pretty_message)
    # return header + pretty_message // No longer required


def main():
    parser = argparse.ArgumentParser('qif2ofx')
    parser.add_argument('--glob', required=True, help='Glob expression for QIF files, for example "./data/**/*.qif"')
    parser.add_argument('--currency', required=False, help='Currency, example: GBP', default='AUD')
    parser.add_argument('--acctid', required=False,
                        help='Account ID. Important for reconciling transactions. Example: "Halifax123"',
                        default="Main")
    parser.add_argument('--trnuid', required=False, help='Client ID. 1234 if unspecified.', default='1234')
    parser.add_argument('--org', required=False, help='Org to set in the OFX. "BankOfEvil" if not supplied',
                        default="BankOfEvil")
    parser.add_argument('--balance', required=False, help='Start Balance of the QIF files, or zero if unspecified',
                        default='0')

    args = parser.parse_args()

    os.chdir(args.glob)
    for file in glob("*.qif"):
        print(os.path.splitext(file)[0])
        fileName = os.path.splitext(file)[0]
        match fileName:
            case fileName if "Qif" in fileName:
                args.org = "Suncorp"
            case fileName if "TranHist" in fileName:
                args.org = "HSBC"

        qif = QIFFile.parse_files(file)
        # print(
        genofx(
            qif,
            file,
            args.currency,
            args.acctid,
            args.trnuid,
            args.org,
            args.balance
        )
    # )
