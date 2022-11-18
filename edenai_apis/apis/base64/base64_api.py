from io import BufferedReader
from itertools import zip_longest
import json
from pprint import pprint
from typing import Dict, Sequence, TypeVar, Union
from collections import defaultdict
import mimetypes
import base64
from enum import Enum
import requests
from edenai_apis.features.ocr.identity_parser.identity_parser_dataclass import (
    IdentityParserDataClass,
    InfoCountry,
    get_info_country,
    InfosIdentityParserDataClass
)
from edenai_apis.features.ocr.invoice_parser import (
    CustomerInformationInvoice,
    InfosInvoiceParserDataClass,
    InvoiceParserDataClass,
    ItemLinesInvoice,
    LocaleInvoice,
    MerchantInformationInvoice,
    TaxesInvoice,
)
from edenai_apis.features.ocr.receipt_parser import (
    CustomerInformation,
    InfosReceiptParserDataClass,
    ItemLines,
    Locale,
    MerchantInformation,
    ReceiptParserDataClass,
    Taxes,
)

from edenai_apis.loaders.data_loader import ProviderDataEnum
from edenai_apis.loaders.loaders import load_provider
from edenai_apis.features import ProviderApi, Ocr
from edenai_apis.utils.conversion import (
    combine_date_with_time,
    convert_string_to_number,
    retreive_first_number_from_string,
)
from edenai_apis.utils.exception import ProviderException
from edenai_apis.utils.types import ResponseType


class SubfeatureParser(Enum):
    RECEIPT = "receipt"
    INVOICE = "invoice"


T = TypeVar("T")


class Base64Api(ProviderApi, Ocr):
    provider_name = "base64"

    def __init__(self) -> None:
        self.api_settings = load_provider(ProviderDataEnum.KEY, self.provider_name)
        self.api_key = self.api_settings["secret"]
        self.url = self.api_settings["endpoint"]

    def _extract_item_lignes(
        self, data, item_lines_type: Union[ItemLines, ItemLinesInvoice]
    ) -> list:
        items_description = [
            value["value"]
            for key, value in data.items()
            if key.startswith("lineItem") and key.endswith("Description")
        ]
        items_quantity = [
            value["value"]
            for key, value in data.items()
            if key.startswith("lineItem") and key.endswith("Quantity")
        ]
        items_unit_price = [
            value["value"]
            for key, value in data.items()
            if key.startswith("lineItem") and key.endswith("UnitPrice")
        ]
        items_total_cost = [
            value["value"]
            for key, value in data.items()
            if key.startswith("lineItem") and key.endswith("LineTotal")
        ]

        items: Sequence[item_lines_type] = []
        for item in zip_longest(
            items_description,
            items_quantity,
            items_total_cost,
            items_unit_price,
            fillvalue=None,
        ):
            item_quantity = retreive_first_number_from_string(
                item[1]
            )  # avoid cases where the quantity is concatenated with a string
            items.append(
                item_lines_type(
                    description=item[0] if item[0] else "",
                    quantity=convert_string_to_number(item_quantity, int),
                    amount=convert_string_to_number(item[2], float),
                    unit_price=convert_string_to_number(item[3], float),
                )
            )
        return items

    def _format_invoice_document_data(self, data) -> InvoiceParserDataClass:
        fields = data[0].get("fields", [])

        items: Sequence[ItemLinesInvoice] = self._extract_item_lignes(
            fields, ItemLinesInvoice
        )

        default_dict = defaultdict(lambda: None)
        invoice_number = fields.get("invoiceNumber", default_dict)["value"]
        invoice_total = fields.get("total", default_dict)["value"]
        invoice_total = convert_string_to_number(invoice_total, float)
        date = fields.get("invoiceDate", default_dict)["value"]
        time = fields.get("invoiceTime", default_dict)["value"]
        date = combine_date_with_time(date, time)
        due_date = fields.get("dueDate", default_dict)["value"]
        due_time = fields.get("dueTime", default_dict)["value"]
        due_date = combine_date_with_time(due_date, due_time)
        invoice_subtotal = fields.get("subtotal", default_dict)["value"]
        invoice_subtotal = convert_string_to_number(invoice_subtotal, float)
        customer_name = fields.get("billTo", default_dict)["value"]
        merchant_name = fields.get("companyName", default_dict)["value"]
        currency = fields.get("currency", default_dict)["value"]

        taxe = fields.get("tax", default_dict)["value"]
        taxe = convert_string_to_number(taxe, float)
        taxes: Sequence[TaxesInvoice] = [(TaxesInvoice(value=taxe))]
        invoice_parser = InfosInvoiceParserDataClass(
            invoice_number=invoice_number,
            date=date,
            due_date=due_date,
            locale=LocaleInvoice(currency=currency),
            customer_information=CustomerInformationInvoice(
                customer_name=customer_name
            ),
            merchant_information=MerchantInformationInvoice(
                merchant_name=merchant_name
            ),
            invoice_total=invoice_total,
            invoice_subtotal=invoice_subtotal,
            item_lines=items,
            taxes=taxes,
        )

        standarized_response = InvoiceParserDataClass(extracted_data=[invoice_parser])

        return standarized_response

    def _format_receipt_document_data(self, data) -> ReceiptParserDataClass:
        fields = data[0].get("fields", [])

        items: Sequence[ItemLines] = self._extract_item_lignes(fields, ItemLines)

        default_dict = defaultdict(lambda: None)
        invoice_number = fields.get("invoiceNumber", default_dict)["value"]
        invoice_total = fields.get("total", default_dict)["value"]
        invoice_total = convert_string_to_number(invoice_total, float)
        date = fields.get("date", default_dict)["value"]
        time = fields.get("time", default_dict)["value"]
        date = combine_date_with_time(date, time)
        invoice_subtotal = fields.get("subtotal", default_dict)["value"]
        invoice_subtotal = convert_string_to_number(invoice_subtotal, float)
        customer_name = fields.get("shipTo", default_dict)["value"]
        merchant_name = fields.get("companyName", default_dict)["value"]
        currency = fields.get("currency", default_dict)["value"]

        taxe = fields.get("tax", default_dict)["value"]
        taxe = convert_string_to_number(taxe, float)
        taxes: Sequence[Taxes] = [(Taxes(taxes=taxe))]
        receipt_infos = {
            "payment_code": fields.get("paymentCode", default_dict)["value"],
            "host": fields.get("host", default_dict)["value"],
            "payment_id": fields.get("paymentId", default_dict)["value"],
            "card_type": fields.get("cardType", default_dict)["value"],
            "receipt_number": fields.get("receiptNo", default_dict)["value"],
        }

        receipt_parser = InfosReceiptParserDataClass(
            invoice_number=invoice_number,
            invoice_total=invoice_total,
            invoice_subtotal=invoice_subtotal,
            locale=Locale(currency=currency),
            merchant_information=MerchantInformation(merchant_name=merchant_name),
            date=str(date),
            receipt_infos=receipt_infos,
            item_lines=items,
            taxes=taxes,
            customer_information=CustomerInformation(customer_name=customer_name),
        )

        standarized_response = ReceiptParserDataClass(extracted_data=[receipt_parser])

        return standarized_response

    def _send_ocr_document(self, file: BufferedReader, model_type: str) -> Dict:
        image_as_base64 = (
            f"data:{mimetypes.guess_type(file.name)[0]};base64,"
            + base64.b64encode(file.read()).decode()
        )

        data = {"modelTypes": [model_type], "image": image_as_base64}

        headers = {"Content-type": "application/json", "Authorization": self.api_key}

        response = requests.post(url=self.url, headers=headers, json=data)

        if response.status_code != 200:
            print("base64 response.text", response.text)
            raise ProviderException(response.text)

        return response.json()

    def _ocr_finance_document(
        self, ocr_file, document_type: SubfeatureParser
    ) -> ResponseType[T]:
        original_response = self._send_ocr_document(
            ocr_file, "finance/" + document_type.value
        )
        if document_type == SubfeatureParser.RECEIPT:
            standarized_response = self._format_receipt_document_data(original_response)
        elif document_type == SubfeatureParser.INVOICE:
            standarized_response = self._format_invoice_document_data(original_response)

        result = ResponseType[T](
            original_response=original_response,
            standarized_response=standarized_response,
        )
        return result

    def ocr__ocr(self, file: BufferedReader, language: str):
        raise ProviderException(
            message="This provider is depricated. You won't be charged for your call."
        )

    def ocr__invoice_parser(
        self, file: BufferedReader, language: str
    ) -> ResponseType[InvoiceParserDataClass]:
        return self._ocr_finance_document(file, SubfeatureParser.INVOICE)

    def ocr__receipt_parser(
        self, file: BufferedReader, language: str
    ) -> ResponseType[ReceiptParserDataClass]:
        return self._ocr_finance_document(file, SubfeatureParser.RECEIPT)

    def ocr__identity_parser(
        self,
        file: BufferedReader,
        filename: str
    ) -> ResponseType[IdentityParserDataClass]:
        image_as_base64 = (
            f"data:{mimetypes.guess_type(file.name)[0]};base64,"
            + base64.b64encode(file.read()).decode()
        )

        payload = json.dumps({
            "image": image_as_base64
        })
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': self.api_key
        }
        
        response = requests.post(url=self.url, headers=headers, data=payload)
        
        original_response = response.json()
        if response.status_code != 200:
            raise ProviderException(message=original_response['message'])

        items = []

        for document in original_response:
            image_id=[doc.get('image', []) for doc in document['features'].get('faces', {})]
            image_signature=[doc.get('image', []) for doc in document['features'].get('signatures', {})]
            given_names=document['fields'].get('givenName', {}).get('value', "").split(' ') if document['fields'].get('givenName', {}).get('value', "") != "" else []
            
            items.append(InfosIdentityParserDataClass(
                document_type=document['fields'].get('documentType', {}).get('value'),
                last_name=document['fields'].get('familyName', {}).get('value', None),
                given_names=given_names,
                birth_date=document['fields'].get('dateOfBirth', {}).get('value', None),
                country=get_info_country(key=InfoCountry.ALPHA3, value=document['fields'].get('countryCode', {}).get('value', "")),
                document_id=document['fields'].get('documentNumber', {}).get('value', None),
                age=document['fields'].get('age', {}).get('value', None),
                nationality=document['fields'].get('nationality', {}).get('value', None),
                issuing_state=document['fields'].get('issuingState', {}).get('value', None),
                image_id=image_id,
                image_signature=image_signature,
                gender=document['fields'].get('sex', {}).get('value'),
                expire_date=document['fields'].get('expirationDate', {}).get('value'),
                issuance_date=document['fields'].get('issueDate', {}).get('value'),
                address=document['fields'].get('address', {}).get('value'),
            ))


        standarized_response = IdentityParserDataClass(extracted_data=items)

        return ResponseType[IdentityParserDataClass](
            original_response=original_response,
            standarized_response=standarized_response,
        )
