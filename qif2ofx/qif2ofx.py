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
from ofxtools.Parser import OFXTree

from .qif import QIFFile


def qif_to_stmttrn(qif_file, savings):
    stmttrns = []
    for transaction in qif_file.transactions:
        dtposted = transaction.date.replace(tzinfo=UTC)
        trnamt = transaction.amount
        if(savings): # Reverse transaction if savings!
            trnamt = trnamt*-1
        trntype = 'DEBIT' if trnamt < 0 else 'CREDIT'
        name = transaction.payee.replace("036", "").rstrip()
        # Some reason, HSBC randomly adds a 036 to approved creditcard...
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


def genofx(qif_file, file_dir, currency, acctid, trnuid, org, balance, accttype):
    trans = qif_to_stmttrn(qif_file, accttype.upper() == "SAVINGS")

    balamt = Decimal(balance) + qif_file.balance()
    ledgerbal = m.LEDGERBAL(balamt=balamt, dtasof=qif_file.last_transaction_date())
    fi = m.FI(org=org, fid='666')  # Required for Quicken compatibility
    banktranlist = m.BANKTRANLIST(*trans, dtstart=datetime(2019, 1, 1, 12, tzinfo=UTC),
                                  dtend=datetime(2018, 1, 1, 12, tzinfo=UTC))
    status = m.STATUS(code=0, severity='INFO')
    sonrs = m.SONRS(status=status,
                    dtserver=datetime.now(tz=UTC),
                    language='ENG', fi=fi)
    signonmsgs = m.SIGNONMSGSRSV1(sonrs=sonrs)

    if(accttype.upper() == "SAVINGS"):
        # Savings account
        bankacctfrom = m.BANKACCTFROM(bankid=org, acctid=acctid, accttype="SAVINGS")  # OFX Section 11.3.1
        stmtrs = m.STMTRS(curdef=currency, bankacctfrom=bankacctfrom, banktranlist=banktranlist, ledgerbal=ledgerbal)
        stmttrnrs = m.STMTTRNRS(trnuid=trnuid, status=status, stmtrs=stmtrs)
        bankmsgsrsv1 = m.BANKMSGSRSV1(stmttrnrs)
        ofx = m.OFX(signonmsgsrsv1=signonmsgs, bankmsgsrsv1=bankmsgsrsv1)
    else:
        # # Credit card
        ccacctfrom = m.CCACCTFROM(acctid=acctid)  # OFX Section 11.3.1
        ccstmtrs = m.CCSTMTRS(curdef=currency, ccacctfrom=ccacctfrom, banktranlist=banktranlist, ledgerbal=ledgerbal)
        ccstmttrnrs = m.CCSTMTTRNRS(trnuid=trnuid, status=status, ccstmtrs=ccstmtrs)
        ccmsgsrsv1 = m.CREDITCARDMSGSRSV1(ccstmttrnrs)
        ofx = m.OFX(signonmsgsrsv1=signonmsgs, creditcardmsgsrsv1=ccmsgsrsv1)

    root = ofx.to_etree()
    message = ET.tostring(root).decode()
    pretty_message = minidom.parseString(message).toprettyxml()
    header = str(make_header(version=220))

    file = "OfxFix_" + os.path.splitext(file_dir)[0] + '.ofx'  # /create ofx file
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
    parser.add_argument('--accttype', required=False, help='Type of account, example: SAVINGS. "CD" if not supplied',
                        default='CD')

    args = parser.parse_args()

# Handling ofx files here first
    print("Testing ofx change")
    os.chdir(args.glob)
    for file in glob("*.[ofx qfx]*"):
        if not file.startswith("OfxFix"):
            parser = OFXTree()
            ofx = parser.parse(file)
            # ofx = parser.convert()

            # for AAA in ofx.findall('STMTTRN'):
            # # for AAA in ofx.iter('STMTTRN'):
            #     if AAA.find('FITID'):
            #         AAA.find('FITID').text = AAA.find('DTPOSTED') + AAA.find('TRNAMT') + AAA.find('NAME')

            # Fix badly designed STMTTRN, iterate and add date
            for trn in ofx.iter('STMTTRN'):
                fitid = '{}{}{}'.format(trn.find("DTPOSTED").text[0:14],trn.find("TRNAMT").text,trn.find("NAME").text.replace(" ", ""))
                print(fitid)
                trn.find("FITID").text = fitid

            message = ET.tostring(ofx).decode()
            pretty_message = minidom.parseString(message).toprettyxml()
            header = str(make_header(version=220))
            file = "OfxFix_" + os.path.splitext(file)[0] + '.ofx'  # overwrite ofx file
            print("Creating ofx file: " + file)
            with open(file, 'w') as filetowrite:
                filetowrite.write(header + pretty_message)

# Handling .qif files
    for file in glob("*.qif"):
        if not file.startswith("OfxFix"):
            # print(os.path.splitext(file)[0])
            file_name = os.path.splitext(file)[0]
            match file_name:
                case file_name if "Qif" in file_name:
                    args.org = "Suncorp"
                    args.acctid = "SuncorpMain"
                    args.accttype="SAVINGS"
                case file_name if "TranHist" in file_name:
                    args.org = "HSBC"
                    args.acctid = "HSBCcc"
                    args.accttype="CD"

            qif = QIFFile.parse_files(file)
            # print(
            genofx(
                qif,
                file,
                args.currency,
                args.acctid,
                args.trnuid,
                args.org,
                args.balance,
                args.accttype
            )
        # )

# from ofxparse import OfxParser
# # with codecs.open('file.ofx') as fileobj:
#     ofx = OfxParser.parse(fileobj)
#
# # The OFX object
#
# ofx.account               # An Account object
#
# # AccountType
# # (Unknown, Bank, CreditCard, Investment)
#
# # Account
#
# account = ofx.account
# account.account_id        # The account number
# account.number            # The account number (deprecated -- returns account_id)
# account.routing_number    # The bank routing number
# account.branch_id         # Transit ID / branch number
# account.type              # An AccountType object
# account.statement         # A Statement object
# account.institution       # An Institution object
#
# # InvestmentAccount(Account)
#
# account.brokerid          # Investment broker ID
# account.statement         # An InvestmentStatement object
#
# # Institution
#
# institution = account.institution
# institution.organization
# institution.fid
#
# # Statement
#
# statement = account.statement
# statement.start_date          # The start date of the transactions
# statement.end_date            # The end date of the transactions
# statement.balance             # The money in the account as of the statement date
# statement.available_balance   # The money available from the account as of the statement date
# statement.transactions        # A list of Transaction objects
#
# # InvestmentStatement
#
# statement = account.statement
# statement.positions           # A list of Position objects
# statement.transactions        # A list of InvestmentTransaction objects
#
# # Transaction
#
# for transaction in statement.transactions:
#     transaction.payee
#     transaction.type
#     transaction.date
#     transaction.user_date
#     transaction.amount
#     transaction.id
#     transaction.memo
#     transaction.sic
#     transaction.mcc
#     transaction.checknum
#
# # InvestmentTransaction
#
# for transaction in statement.transactions:
#     transaction.type
#     transaction.tradeDate
#     transaction.settleDate
#     transaction.memo
#     transaction.security      # A Security object
#     transaction.income_type
#     transaction.units
#     transaction.unit_price
#     transaction.comission
#     transaction.fees
#     transaction.total
#     transaction.tferaction
#
# # Positions
#
# for position in statement.positions:
#     position.security       # A Security object
#     position.units
#     position.unit_price
#     position.market_value
#
# # Security
#
# security = transaction.security
# # or
# security = position.security
# security.uniqueid
# security.name
# security.ticker
# security.memo