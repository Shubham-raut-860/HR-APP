import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Briefcase, Building2, Clock3, MapPin, ShieldCheck, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getPublicJob } from "@/services/candidatePortal";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default function PublicJobShare() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = React.useState<any>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    async function load() {
      if (!id) return;
      setLoading(true);
      setError(null);
      if (!UUID_RE.test(id)) {
        setJob(null);
        setError("This job link is unavailable or the role is no longer open.");
        setLoading(false);
        return;
      }
      try {
        const data = await getPublicJob(id);
        if (alive) setJob(data);
      } catch {
        if (alive) setError("This job link is unavailable or the role is no longer open.");
      } finally {
        if (alive) setLoading(false);
      }
    }
    void load();
    return () => {
      alive = false;
    };
  }, [id]);

  const redirectPath = `/candidate/jobs/${id || ""}`;
  const loginHref = `/login?redirect=${encodeURIComponent(redirectPath)}`;
  const signupHref = `/signup?redirect=${encodeURIComponent(redirectPath)}`;

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(15,23,42,0.10),transparent_34%),linear-gradient(180deg,#f8fafc,white)] px-4 py-8 text-foreground dark:bg-background">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-between gap-3">
          <Link to="/" className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
            Jobora
          </Link>
          <Badge variant="outline" className="rounded-full bg-background/80">
            Public job link
          </Badge>
        </div>

        {loading ? (
          <Card className="overflow-hidden rounded-3xl border-border/60 shadow-sm">
            <CardContent className="space-y-5 p-8">
              <Skeleton className="h-10 w-2/3" />
              <Skeleton className="h-5 w-1/2" />
              <div className="grid gap-3 sm:grid-cols-3">
                <Skeleton className="h-20 rounded-2xl" />
                <Skeleton className="h-20 rounded-2xl" />
                <Skeleton className="h-20 rounded-2xl" />
              </div>
              <Skeleton className="h-40 rounded-2xl" />
            </CardContent>
          </Card>
        ) : error ? (
          <Card className="rounded-3xl border-dashed">
            <CardContent className="p-10 text-center">
              <p className="text-lg font-semibold">Job not available</p>
              <p className="mt-2 text-sm text-muted-foreground">{error}</p>
              <Button asChild className="mt-6 rounded-xl">
                <Link to="/login">Sign in</Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <>
            <section className="rounded-[2rem] border bg-background/90 p-7 shadow-sm backdrop-blur">
              <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
                <div className="max-w-3xl space-y-4">
                  <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Verified opening
                  </div>
                  <div>
                    <h1 className="text-3xl font-bold tracking-tight sm:text-5xl">{job.title}</h1>
                    <p className="mt-3 max-w-2xl text-base text-muted-foreground">
                      {job.company ? `${job.company} is hiring for ${job.role}.` : `Open role for ${job.role}.`}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary" className="rounded-full gap-1.5"><MapPin className="h-3.5 w-3.5" />{job.location || "Remote"}</Badge>
                    <Badge variant="secondary" className="rounded-full gap-1.5"><Briefcase className="h-3.5 w-3.5" />{job.employment_type || "Full-time"}</Badge>
                    <Badge variant="secondary" className="rounded-full gap-1.5"><Clock3 className="h-3.5 w-3.5" />{job.experience_min}-{job.experience_max} yrs</Badge>
                  </div>
                </div>
                <Card className="w-full rounded-3xl lg:w-80">
                  <CardContent className="space-y-3 p-5">
                    <p className="text-sm font-semibold">Ready to apply?</p>
                    <p className="text-xs text-muted-foreground">
                      Sign in as a candidate to upload your resume, see fit scoring, and track progress.
                    </p>
                    <Button asChild className="w-full rounded-xl">
                      <Link to={loginHref}>Sign in to apply</Link>
                    </Button>
                    <Button asChild variant="outline" className="w-full rounded-xl">
                      <Link to={signupHref}>Create candidate account</Link>
                    </Button>
                  </CardContent>
                </Card>
              </div>
            </section>

            <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
              <Card className="rounded-3xl">
                <CardContent className="space-y-4 p-6">
                  <h2 className="text-lg font-semibold">Role overview</h2>
                  <p className="whitespace-pre-wrap text-sm leading-7 text-muted-foreground">
                    {job.description || "The recruiter has not added a long description yet."}
                  </p>
                </CardContent>
              </Card>
              <div className="space-y-4">
                <Card className="rounded-3xl">
                  <CardContent className="space-y-3 p-5">
                    <h2 className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-primary" />Required skills</h2>
                    <div className="flex flex-wrap gap-2">
                      {(job.must_have_skills || []).length ? job.must_have_skills.map((skill: string) => (
                        <Badge key={skill} variant="outline" className="rounded-full">{skill}</Badge>
                      )) : <p className="text-sm text-muted-foreground">No must-have skills listed.</p>}
                    </div>
                  </CardContent>
                </Card>
                <Card className="rounded-3xl">
                  <CardContent className="space-y-3 p-5">
                    <h2 className="flex items-center gap-2 text-sm font-semibold"><Building2 className="h-4 w-4 text-primary" />Company</h2>
                    <p className="text-sm font-medium">{job.company || "Hiring team"}</p>
                    {job.company_bio && <p className="text-sm text-muted-foreground">{job.company_bio}</p>}
                  </CardContent>
                </Card>
              </div>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
