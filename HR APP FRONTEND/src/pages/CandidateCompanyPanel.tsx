import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Building, Globe, ArrowLeft, Users, MapPin, Briefcase, AlertCircle } from "lucide-react";
import { getPublicJob } from "@/services/candidatePortal";

export default function CandidateCompanyPanel() {
  const { id }     = useParams();
  const navigate   = useNavigate();
  const [job, setJob]         = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(false);

  useEffect(() => {
    const fetchJob = async () => {
      if (!id) { setLoading(false); setError(true); return; }
      try {
        // BUG FIX: was calling getPublicJobs() and searching the array, which
        // downloads *all* jobs just to find one. Use the direct endpoint instead.
        // Also removed all localStorage fallbacks — candidates are different users
        // from HRs; their localStorage won't have the recruiter's company data.
        const data = await getPublicJob(id);
        setJob(data);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    };
    fetchJob();
  }, [id]);

  if (loading) return (
    <div className="p-12 text-center animate-pulse text-muted-foreground">
      Loading company profile...
    </div>
  );

  if (error || !job) return (
    <div className="max-w-md mx-auto mt-16 text-center space-y-4">
      <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mx-auto">
        <AlertCircle className="h-6 w-6 text-muted-foreground" />
      </div>
      <h2 className="font-semibold text-lg">Company profile not found</h2>
      <p className="text-sm text-muted-foreground">This listing may have been removed or the link is invalid.</p>
      <Button variant="outline" className="rounded-full" onClick={() => navigate(-1)}>
        <ArrowLeft className="h-4 w-4 mr-2" /> Go Back
      </Button>
    </div>
  );

  // BUG FIX: all company data comes from the job record itself — no localStorage fallback.
  // Fallback strings are generic but honest rather than silently showing a recruiter's data.
  const companyName    = job.company      || "Company";
  const companyBio     = job.company_bio  || "We are actively looking for top talent. Apply to our open roles to learn more about our mission and culture!";
  const companyWebsite = job.company_blog || null;

  return (
    <div className="max-w-5xl mx-auto space-y-8 animate-in fade-in duration-500">
      <Button variant="ghost" onClick={() => navigate(-1)} className="mb-2 rounded-full hover:bg-muted/50 transition-colors">
        <ArrowLeft className="h-4 w-4 mr-2" /> Back to Job Board
      </Button>

      {/* Hero */}
      <div className="relative rounded-3xl overflow-hidden bg-gradient-to-br from-primary/5 via-background to-muted/20 border border-border/50 p-8 md:p-12 shadow-sm">
        <div className="flex flex-col md:flex-row gap-8 items-start md:items-center">
          <div className="h-28 w-28 bg-card rounded-3xl flex items-center justify-center border border-border shadow-sm shrink-0">
            <Building className="h-12 w-12 text-primary/40" />
          </div>
          <div className="space-y-3 flex-1">
            <h1 className="text-4xl font-bold tracking-tight text-foreground">{companyName}</h1>
            <div className="flex flex-wrap gap-4 text-muted-foreground font-medium">
              <span className="flex items-center text-sm bg-background px-3 py-1 rounded-full border border-border/50">
                <MapPin className="h-4 w-4 mr-1.5 opacity-70" /> {job.location || "Global HQ"}
              </span>
              <span className="flex items-center text-sm bg-background px-3 py-1 rounded-full border border-border/50">
                <Users className="h-4 w-4 mr-1.5 opacity-70" /> Actively Hiring
              </span>
            </div>
          </div>
          {companyWebsite && (
            <Button asChild className="rounded-full shadow-sm px-6 h-12">
              <a href={companyWebsite.startsWith('http') ? companyWebsite : `https://${companyWebsite}`} target="_blank" rel="noopener noreferrer">
                <Globe className="mr-2 h-4 w-4" /> Visit Website
              </a>
            </Button>
          )}
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-8">
        {/* Bio */}
        <div className="md:col-span-2 space-y-8">
          <Card className="shadow-sm border-border/50 overflow-hidden">
            <CardHeader className="bg-muted/10 border-b border-border/40 pb-4">
              <CardTitle className="text-xl">About the Company</CardTitle>
            </CardHeader>
            <CardContent className="p-6">
              <p className="text-muted-foreground leading-relaxed whitespace-pre-wrap text-[15px]">
                {companyBio}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Sidebar: featured opening */}
        <div className="space-y-6">
          <h3 className="text-lg font-semibold tracking-tight">Featured Opening</h3>
          <Card className="hover:border-primary/40 hover:shadow-md transition-all duration-300 group">
            <CardContent className="p-5 flex flex-col gap-4">
              <div>
                <h4 className="font-semibold text-foreground group-hover:text-primary transition-colors">{job.title}</h4>
                <p className="text-sm text-muted-foreground mt-1 flex items-center gap-1.5">
                  <Briefcase className="h-3.5 w-3.5" /> {job.employment_type || "Full-time"}
                </p>
              </div>
              <Button asChild variant="default" className="w-full rounded-xl">
                <Link to={`/candidate/jobs/${job.id}`}>View & Apply</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
