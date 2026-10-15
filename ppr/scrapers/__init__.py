from ppr.scrapers.acl import SCRAPERS as ACL_SCRAPERS
from ppr.scrapers.aaai import SCRAPERS as AAAI_SCRAPERS
from ppr.scrapers.usenix import SCRAPERS as USENIX_SCRAPERS
from ppr.scrapers.dblp import SCRAPERS as DBLP_SCRAPERS
from ppr.scrapers.researchr import SCRAPERS as RESEARCHR_SCRAPERS
from ppr.scrapers.cvf import SCRAPERS as CVF_SCRAPERS
from ppr.scrapers.rss import SCRAPERS as RSS_SCRAPERS
from ppr.scrapers.ijcai import SCRAPERS as IJCAI_SCRAPERS

SCRAPERS = {
    **ACL_SCRAPERS,
    **AAAI_SCRAPERS,
    **USENIX_SCRAPERS,
    **DBLP_SCRAPERS,
    **RESEARCHR_SCRAPERS,
    **CVF_SCRAPERS,
    **RSS_SCRAPERS,
    **IJCAI_SCRAPERS,
}
