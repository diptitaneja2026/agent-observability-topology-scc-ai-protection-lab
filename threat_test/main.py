import asyncio
import os
import subprocess
import socket
import vertexai
from vertexai import Client, agent_engines
from google.adk.agents import llm_agent
from google.adk.sessions.in_memory_session_service import InMemorySessionService

# Replace with your own project, location, and staging bucket.
LOCATION = "us-central1"
PROJECT_ID = "qwiklabs-gcp-01-f67f64703dca"
# Staging bucket must have gs:// prefix
STAGING_BUCKET = "gs://qwiklabs-gcp-01-f67f64703dca-bucket"

client = Client(project=PROJECT_ID, location=LOCATION)

def _run_command(args, **kwargs):
  output = f"Called {' '.join(args)}\n"
  try:
    res = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if res.stdout:
      output += f"Result: {res.stdout.strip()}\n"
    if res.stderr:
      output += f"Error: {res.stderr.strip()}\n"
  except subprocess.TimeoutExpired:
    output += "Command timed out as expected."
  return output

# Tool to simulate threats (Execution: Added Malicious Binary Executed using EICAR test file).
def threat_detection_test():
  output = _run_command(["sleep", "60"])
  eicar = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
  output += _run_command(["touch", "/tmp/test_mal_file"])
  with open("/tmp/test_mal_file", "w") as f:
    f.write(eicar)
  output += _run_command(["chmod", "700", "/tmp/test_mal_file"])
  output += _run_command(["sh", "-c", "/tmp/test_mal_file"])
  output += _run_command(["sleep", "10"])
  return output

root_agent = llm_agent.Agent(
    model="gemini-2.5-flash",
    name="threat_detection_test_agent",
    description="Runs threat detection test.",
    instruction="""
      You are an agent that runs a threat detection test using a fake malicious
      command.
    """,
    tools=[threat_detection_test],
)

async def main():
  vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
    staging_bucket=STAGING_BUCKET,
  )
  app = agent_engines.AdkApp(
      agent=root_agent, session_service_builder=InMemorySessionService
  )
  remote_agent = client.agent_engines.create(
      agent=app,
      config={
          "display_name": "scc_threat_test_agent",
          "identity_type": vertexai.types.IdentityType.AGENT_IDENTITY,
          "requirements": [
              "google-cloud-aiplatform[agent_engines,adk]",
              "cloudpickle",
              "pydantic",
          ],
          "staging_bucket": STAGING_BUCKET,
          "extra_packages": [
              "installation_scripts/install.sh",
          ],
      },
  )
  print("Deployed agent: ", remote_agent.api_resource.name)

  try:
      async for event in remote_agent.async_stream_query(
          user_id="threat_detection_tester",
          message="Run the threat detection test",
      ):
        print(event)
  finally:
      client.agent_engines.delete(name=remote_agent.api_resource.name, force=True)

if __name__ == "__main__":
  asyncio.run(main())
