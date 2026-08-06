FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:8.0
# Knative's default PodSecurityContext requires runAsNonRoot; the base image
# defaults to root, but ships a pre-created "app" user (APP_UID) for this.
USER $APP_UID
WORKDIR /app
COPY --from=build /app .
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "Function.dll"]
