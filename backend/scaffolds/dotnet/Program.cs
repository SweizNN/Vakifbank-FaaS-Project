using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Abstractions;
using Microsoft.AspNetCore.Mvc.Infrastructure;
using Microsoft.AspNetCore.Routing;

var builder = WebApplication.CreateBuilder(args);

// The Function.cs wrapper (see frontend/js/templates.js wrapCode) reads
// request.Body synchronously via StreamReader.ReadToEnd(), which Kestrel
// rejects by default (AllowSynchronousIO=false since .NET Core 3.0).
builder.WebHost.ConfigureKestrel(o => o.AllowSynchronousIO = true);

// Minimal APIs don't execute IActionResult the way MVC does — returning one
// directly from a Map* delegate just JSON-serializes the IActionResult
// object itself (its Value/Formatters/StatusCode properties), not the
// response it represents. AddControllers() registers IActionResultExecutor<T>
// in DI so ExecuteResultAsync() below runs it properly, without needing any
// actual MVC controllers/attribute routing.
builder.Services.AddControllers();

var app = builder.Build();

async Task Invoke(HttpContext context)
{
    var logger = context.RequestServices.GetRequiredService<ILogger<Program>>();
    var result = function.Function.Handle(context.Request, logger);
    var actionContext = new ActionContext(context, new RouteData(), new ActionDescriptor());
    await result.ExecuteResultAsync(actionContext);
}

app.MapGet("/", Invoke);
app.MapPost("/", Invoke);

app.Run();
