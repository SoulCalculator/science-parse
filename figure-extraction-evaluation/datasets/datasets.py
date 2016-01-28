from os import listdir, mkdir
from os.path import join, dirname, isdir, isfile
import json
from pdffigures_utils import Figure

"""
This file defines a number of "Dataset" classes. Dataset classes represent a
collection of PDFs along with gold standard annotations for where the figures and tables
are within each PDF (see the README in this directory). Datasets provide hooks to find the
filepaths of these PDFs, to load the gold standard annotations as python objects, and to load various
others bits of data associate with those PDFS (like test/train ids, locations of cached rasterized pages,
again see the README). Datasets are always associated with a name and this file
exports "get_dataset" which can retrieve a dataset by name
"""

# So file locations work regardless of where scripts are run
BASE_DIR = dirname(__file__)

def get_image_dict(directory):
    if not isdir(directory):
        return None
    data = {}
    for filename in listdir(directory):
        doc_id, page = filename[:filename.rfind(".")].split("-page-")
        if doc_id not in data:
            data[doc_id] = {}
        data[doc_id][int(page)] = join(directory, filename)
    return data

def download_from_urls(doc_id_to_url, output_dir):
    import requests
    already_have = 0
    if not isdir(output_dir):
        print("Making directory %s to store PDFs" % output_dir)
        mkdir(output_dir)
    else:
        for filename in listdir(output_dir):
            if not filename.endswith(".pdf"):
                raise ValueError("File %s id not a PDF file" % filename)
            doc_id = filename[:-4]
            if doc_id not in doc_id_to_url:
                raise ValueError("Document %s has an document that was not recognized" % filename)
            already_have += 1
            del doc_id_to_url[doc_id]
    print("Already have %d documents, need to download %d" % (already_have, len(doc_id_to_url)))

    for i, (doc_id, url) in enumerate(sorted(doc_id_to_url.items())):
        print("Downloading %s (%d of %d)" % (doc_id, i + 1, len(doc_id_to_url)))
        r = requests.get(url)
        r.raise_for_status()
        content = r.content
        try:
            if content.decode("utf-8").startswith("<!DOCTYPE html>"):
                raise ValueError("Appeared to get an HTML file for doc %s url=%s" % (doc_id, url))
        except UnicodeDecodeError:
            pass
        with open(join(output_dir, doc_id + ".pdf"), "wb") as pdf_file:
            pdf_file.write(content)
        r.close()

class Document(object):

    def __init__(self, doc_id, pages_annotated, figures, pdffile, dpi,
                 gray_images=None, color_images=None, non_standard=False):

        if non_standard is not None and not isinstance(non_standard, bool):
            raise ValueError()
        if not isfile(pdffile):
            raise ValueError()
        if not isinstance(dpi, int):
            raise ValueError()

        self.doc_id = doc_id
        self.dpi = dpi
        self.pages_annotated = pages_annotated
        self.figures = figures
        self.gray_images = gray_images
        self.color_images = color_images
        self.pdffile = pdffile
        self.non_standard = non_standard


class Dataset(object):
    """
    Represents a Dataset of PDFs and their labels we can use to evaluate extractors on. Also includes
    some pre-processed data such images of each page of the PDF.
    """

    PDFS = "pdfs"
    PAGE_IMAGES_COLOR = "page_images_color"
    PAGE_IMAGES_GRAY = "page_images_gray"
    ANNOTATIONS = "annotations.json"
    TEST_IDS = "test_ids.txt"
    PAGES_ANNOTATED = "pages_annotated.json"
    NON_STANDARD_DOCS = "non_standard_documents.txt"

    def __init__(self, name, directory, version, image_dpi):
        self.dir = directory
        self.name = name
        self.version = version
        self.pdf_dir = join(directory, self.PDFS)
        self.image_dpi = image_dpi
        self.page_images_color_dir = join(directory, self.PAGE_IMAGES_COLOR)
        self.page_images_gray_dir = join(directory, self.PAGE_IMAGES_GRAY)
        self.annotation_file = join(directory, self.ANNOTATIONS)
        self.test_ids_file = join(directory, self.TEST_IDS)
        self.pages_annotated_file = join(directory, self.PAGES_ANNOTATED)
        self.non_standard_docs_file = join(directory, self.NON_STANDARD_DOCS)

    """ Return document ids that have been marked as being in the test set """
    def get_test_doc_ids(self):
        test_ids = []
        if not isfile(self.test_ids_file):
            raise ValueError("Dataset %s does not have a %s file" % (self.name, self.test_ids_file))
        with open(self.test_ids_file) as f:
            for line in f:
                test_ids.append(line.strip())
        return test_ids

    """ Return all document ids """
    def get_all_doc_ids(self):
        docs = []
        for doc in listdir(self.pdf_dir):
            docs.append(doc[:doc.rfind(".")])
        return docs

    """ Return all document ids that have been marked as being the train set """
    def get_train_doc_ids(self):
        all_ids = self.get_all_doc_ids()
        test_ids = self.get_test_doc_ids()
        return list(set(all_ids) - set(test_ids))

    """ Return all document ids that are in the given partition """
    def get_doc_ids(self, which):
        if which not in ["train", "test", "all"]:
            raise ValueError()
        if which == "train":
            return self.get_train_doc_ids()
        elif which == "test":
            return self.get_test_doc_ids()
        else:
            return self.get_all_doc_ids()

    """ Returns map of document_id -> list of page numbers that were annotated, 1 based, or
        None if all the pages of each PDF were annotated """
    def get_annotated_pages_map(self):
        if isfile(self.pages_annotated_file):
            with open(self.pages_annotated_file) as f:
                return json.load(f)
        else:
            return None

    """ Return the document ids of documents that have been marked as being non-standard """
    def get_nonstandard_doc_ids(self):
        ocr_docs = set()
        if isfile(self.non_standard_docs_file):
            with open(self.non_standard_docs_file) as f:
                for line in f:
                    ocr_docs.add(line.strip().split()[0])
            return ocr_docs
        else:
            return set()

    """ Return a list of `Document` object for all the document in the given partition """
    def load_docs(self, which):
        doc_ids = self.get_doc_ids(which)
        return self.load_doc_ids(doc_ids)

    """ Return a list of `Document` objects for each of the given document ids """
    def load_doc_ids(self, doc_ids):
        pdf_file_map = self.get_pdf_file_map()
        color_image_map = self.get_color_image_file_map()
        gray_image_map = self.get_gray_image_file_map()
        annotations = self.get_annotations("all")
        ocr_docs = self.get_nonstandard_doc_ids()
        documents = []
        for doc_id in doc_ids:
            if doc_id not in annotations:
                raise ValueError("Not annotations for document %s" % doc_id)
            ann = annotations[doc_id]
            non_standard = False
            if ocr_docs is not None:
                non_standard = doc_id in ocr_docs
            documents.append(Document(
                doc_id,
                ann["annotated_pages"],
                ann["figures"],
                pdf_file_map[doc_id],
                self.image_dpi,
                gray_image_map[doc_id] if gray_image_map is not None else None,
                color_image_map[doc_id] if color_image_map is not None else None,
                non_standard=non_standard))
        return documents

    """ Return a list of `Figure` objects and which pages where annotated
        for each of the given document ids """
    def get_annotations(self, which="train"):
        with open(self.annotation_file) as f:
            annotations = json.load(f)
        python_annotations = {}
        doc_ids = set(self.get_doc_ids(which))
        for doc, doc_annotations in annotations.items():
            if doc not in doc_ids:
                continue
            pages = doc_annotations["pages_annotated"]
            figures = []
            for figure in doc_annotations["figures"]:
                figure = Figure.from_dict(figure)
                if not figure.page in pages:
                    raise ValueError()
                figures.append(figure)
            python_annotations[doc] = dict(figures=figures, annotated_pages=pages)
        return python_annotations

    """ Return map of document ids -> path to the pdf file """
    def get_pdf_file_map(self):
        map = {}
        for filename in listdir(self.pdf_dir):
            if not filename.endswith(".pdf"):
                raise ValueError("Non PDF file %s found in PDFs directory" % filename)
            doc = filename[:-4]
            map[doc] = join(self.pdf_dir, filename)
        return map

    """ Return map of document ids -> page number (1 based) -> filepath containing
        the color image of the page,  None if no color images were found"""
    def get_color_image_file_map(self):
        return get_image_dict(join(self.dir, self.PAGE_IMAGES_COLOR))

    """ Return map of document ids -> page number (1 based) -> filepath containing
        the gray image of the page, or None if no gray images were found"""
    def get_gray_image_file_map(self):
        return get_image_dict(join(self.dir, self.PAGE_IMAGES_GRAY))

    """ Return version of the dataset """
    def get_version(self):
        return self.version

    """ Downloads all PDFs for the dataset """
    def fetch_pdfs(self):
        raise NotImplemented()

    """ Return version number the PDFs for this that are stored in the datastore """
    def datastore_version(self):
        raise NotImplemented()


class AclMetaEval(Dataset):
    """
    Papers sampled from ACL and biased towards freshness and high citation count. acl/shuffeled_ids_to_sample_from.txt
    contains additional ACL paper ids that were sampled with the same bias.
    """

    URL_FILE = "urls.txt"
    DIR = "acl"
    NAME = "acl"
    IMAGE_DPI = 150
    # 8: Add OCR documents
    # 9: Fixed annotations for J13-1007
    VERSION = 9

    def __init__(self):
        super().__init__(self.NAME, join(BASE_DIR, self.DIR), self.VERSION, self.IMAGE_DPI)

    def fetch_pdfs(self):
        doc_id_to_url = {}
        with open(join(BASE_DIR, self.DIR, self.URL_FILE)) as f:
            for line in f:
                doc_id, url = line.strip().split(" ")
                doc_id_to_url[doc_id] = url
        download_from_urls(doc_id_to_url, self.pdf_dir)

    def datastore_version(self):
        return 1

    def __eq__(self, other):
        return isinstance(other, AclMetaEval) and self.__dict__ == other.__dict__


class Conference150(Dataset):
    """
    Contains papers sampled from AAAI, NIPS, and ICML from 2009-2015. What pdffigures.allenai.org was
    evaluated on.
    """

    URL_FILE = "urls.txt"
    DIR = "conference"
    NAME = "conference"
    IMAGE_DPI = 150
    VERSION = 2

    def __init__(self):
        super().__init__(self.NAME, join(BASE_DIR, self.DIR), self.VERSION, self.IMAGE_DPI)

    def fetch_pdfs(self):
        doc_id_to_url = {}
        with open(join(BASE_DIR, self.DIR, self.URL_FILE)) as f:
            for line in f:
                doc_id, url = line.strip().split(" ")
                doc_id_to_url[doc_id] = url
        download_from_urls(doc_id_to_url, self.pdf_dir)

    def datastore_version(self):
        return 1

    def __eq__(self, other):
        return isinstance(other, Conference150) and self.__dict__ == other.__dict__

class S2Sample(Dataset):
    """
    Contains papers with 7 or more citations and from a year large than 1999 that were sampled from
    a Pipeline Run 2015.07.15, more specifically we randomly sampled papers that met this criteria from
    ai2-s2/pipeline/output/publish/data/BuildPapers.94f71474981c3d52. These papers all had DBLP matches.
    Additionally pages were sampled from each PDF to help build a large, diverse dataset.
    We annotated 50% of the pages in each PDF and up to 9 pages a PDF.
    """

    DIR = "s2"
    NAME = "s2"
    IMAGE_DPI = 150

    # For sub-sampling pages
    MAX_PAGES_TO_ANNOTATE = 9
    PAGE_SAMPLE_PERCENT = 0.5
    PAGE_SAMPLE_SEED = 0

    # For downloading
    DOC_IDS_FILE = "doc_ids.txt"
    BASE_URL = "http://s3-us-west-2.amazonaws.com/ai2-s2-pdfs/"

    # 6 -> added 5b5c26744406814b0ebba3d640ced78394a79c6c to OCR documents
    # 7 -> Added another 100 annotated docs from Isaac
    # 8 -> Fixed annotations for cd57d5af9a84e7b80cfad8fe7e9572389559612b
    VERSION = 8

    def __init__(self):
        super().__init__(self.NAME, join(BASE_DIR, self.DIR), self.VERSION, self.IMAGE_DPI)

    def fetch_pdfs(self):
        with open(join(BASE_DIR, self.DIR, self.DOC_IDS_FILE)) as f:
            doc_ids = [line.strip() for line in f]
        doc_id_to_url = {doc_id: self.BASE_URL + doc_id[:4] + "/" + doc_id[4:] + ".pdf" for doc_id in doc_ids}
        download_from_urls(doc_id_to_url, self.pdf_dir)

    def datastore_version(self):
        return 1

    def __eq__(self, other):
        return isinstance(other, S2Sample) and self.__dict__ == other.__dict__


DATASETS = {
    AclMetaEval.NAME: AclMetaEval,
    Conference150.NAME: Conference150,
    S2Sample.NAME: S2Sample
}


def get_dataset(name):
    return DATASETS[name]()
